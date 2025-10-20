#!/usr/bin/env python3
##################################
# covergroupgen.py
#
# David_Harris@hmc.edu 15 August 2025
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
#
# Generate functional covergroups for RISC-V instructions
##################################

import csv
import math
import re
import sys
from pathlib import Path
from typing import TextIO

##################################
# Type Definitions
##################################

TestPlans = dict[str, dict[str, list[str]]]
ArchSources = dict[str, str]
CovergroupTemplates = dict[str, str]


##################################
# Functions
##################################


def read_testplans(arch_verif: Path) -> tuple[TestPlans, ArchSources]:
    """Read testplans from CSV files in the testplans directory.

    Iterates over all CSV testplan files and populates a dictionary of dictionaries
    where the top-level key is the architecture (e.g., RV64I) and the second-level
    key is the instruction mnemonic (e.g., add), with the value being a list of
    covergroups for that instruction.

    Args:
        arch_verif: Root path of the architecture verification directory

    Returns:
        A tuple of (testplans, archSources) where:
        - testplans: dict mapping architecture to instruction covergroups
        - archSources: dict mapping architecture to source category ('unpriv' or 'priv')
    """
    testplans: TestPlans = {}
    arch_sources: ArchSources = {}
    coverplan_dirs = [(arch_verif / "testplans", "unpriv"), (arch_verif / "testplans" / "priv", "priv")]

    for coverplan_dir, source in coverplan_dirs:
        if not coverplan_dir.exists():
            continue  # Skip missing directories
        for file in coverplan_dir.iterdir():
            if file.suffix == ".csv":
                match = re.search(r"(.*)\.csv", file.name)
                if match is None:
                    continue
                arch = match.group(1)
                with file.open() as csvfile:
                    reader = csv.DictReader(csvfile)
                    tp: dict[str, list[str]] = {}
                    for row in reader:
                        if "Instruction" not in row:
                            print(
                                f"Error reading testplan {file.name}. "
                                "Did you remember to shrink the .csv files after expanding?"
                            )
                            sys.exit(1)
                        instr = row["Instruction"]
                        cps: list[str] = []
                        del row["Instruction"]
                        for key, value in row.items():
                            if isinstance(value, str) and value != "":
                                if key == "Type":
                                    cps.append("sample_" + value)
                                else:
                                    # For special entries, append the entry name
                                    # (e.g., cp_rd_edges becomes cp_rd_edges_lui)
                                    if value != "x":
                                        key = key + "_" + value
                                    cps.append(key)
                        tp[instr] = cps
                testplans[arch] = tp
                arch_sources[arch] = source
                # Duplicate I testplan for E
                if arch == "I":
                    testplans["E"] = tp
                    arch_sources["E"] = source
                if arch == "Vx":
                    for effew in ["8", "16", "32", "64"]:
                        testplans["Vx" + effew] = tp
                        arch_sources["Vx" + effew] = source
                    del testplans["Vx"]
                    del arch_sources["Vx"]
                if arch == "Vls":
                    for effew in ["8", "16", "32", "64"]:
                        testplans["Vls" + effew] = tp
                        arch_sources["Vls" + effew] = source
                    del testplans["Vls"]
                    del arch_sources["Vls"]
                if arch == "Vf":
                    # SEW of 8 is not supported for vector floating point
                    for effew in ["16", "32", "64"]:
                        testplans["Vf" + effew] = tp
                        arch_sources["Vf" + effew] = source
                    del testplans["Vf"]
                    del arch_sources["Vf"]
    return testplans, arch_sources

def read_covergroup_templates(arch_verif: Path) -> CovergroupTemplates:
    """Read covergroup templates from the templates directory.

    Args:
        arch_verif: Root path of the architecture verification directory

    Returns:
        Dictionary mapping template names to their content
    """
    template_dir = arch_verif / "generators" / "coverage" / "templates"
    covergroup_templates: CovergroupTemplates = {}
    for file in template_dir.iterdir():
        if file.suffix == ".txt":
            match = re.search(r"(.*)\.txt", file.name)
            if match is None:
                continue
            cg = match.group(1)
            covergroup_templates[cg] = file.read_text()
    return covergroup_templates

def customize_template(
    covergroup_templates: CovergroupTemplates,
    name: str,
    arch: str,
    instr: str,
    missing_templates: list[str],
    effew: str = "",
) -> str:
    """Replace placeholders in a covergroup template with actual values.

    Args:
        covergroup_templates: Dictionary of template names to content
        name: Name of the template to customize
        arch: Architecture name (e.g., 'RV64I')
        instr: Instruction mnemonic
        missing_templates: List to track missing templates (mutated in place)
        effew: Effective element width (for vector instructions)

    Returns:
        Customized template string, or empty string if template not found
    """
    if name not in covergroup_templates:
        if name not in missing_templates:
            print(f"No template found for '{name}'. Check if there are spaces before or after coverpoint name.")
            missing_templates.append(name)
        return ""

    template = covergroup_templates[name]
    instr_nodot = instr.replace(".", "_")
    template = template.replace("INSTRNODOT", instr_nodot)
    template = template.replace("INSTR", instr)
    template = template.replace("ARCHUPPER", arch.upper())
    template = template.replace("ARCHCASE", arch)
    template = template.replace("ARCH", arch.lower())
    if effew != "":
        template = template.replace("TWOEFFEW", str(2 * int(effew)))
        template = template.replace("EFFEW", str(int(effew)))
        template = template.replace("EFFVSEW", str(int(math.log2(int(effew))) - 3))
    return template

def any_exclusion(rv: str, instrs: list[str], tp: dict[str, list[str]]) -> bool:
    """Check if any instruction in this extension is not available in the specified RV32 or RV64.

    Args:
        rv: Register variant ('RV32' or 'RV64')
        instrs: List of instruction mnemonics
        tp: Test plan dictionary mapping instructions to coverpoints

    Returns:
        True if any instruction is excluded for the given RV variant
    """
    for instr in instrs:
        cps = tp[instr]
        if rv not in cps:
            return True
    return False


def any_effew_exclusion(effew: str, instrs: list[str], tp: dict[str, list[str]]) -> bool:
    """Check if any instruction is excluded for the given effective element width.

    Args:
        effew: Effective element width
        instrs: List of instruction mnemonics
        tp: Test plan dictionary mapping instructions to coverpoints

    Returns:
        True if any instruction is excluded for the given EFFEW
    """
    for instr in instrs:
        cps = tp[instr]
        if effew not in cps:
            return True
    return False


# SEW-dependent coverpoints that need special handling
SEW_DEPENDENT_CPS = [
    "cp_vs2_edges_f",
    "cp_vs1_edges_f",
    "cp_custom_shift_wv",
    "cp_custom_shift_wx",
    "cp_custom_shift_vv",
    "cp_custom_shift_vx",
    "cp_custom_shift_vi",
    "cp_custom_vindex",
    "cr_vs2_vs1_edges_f",
    "cp_fs1_edges_v",
    "cr_vs2_fs1_edges",
    "cr_vl_lmul",
]

def write_instrs(
    f: TextIO,
    finit: TextIO,
    k: list[str],
    covergroup_templates: CovergroupTemplates,
    tp: dict[str, list[str]],
    arch: str,
    missing_templates: list[str],
    has_rv32: bool,
    has_rv64: bool,
) -> None:
    """Write instructions if they match the specified RV32/RV64 criteria.

    Groups instructions according to which XLEN they are in. Write the instruction
    if it has an 'x' in the listed RV32 and RV64 columns. When has_rv32/64 is false,
    the column must be empty.

    Args:
        f: Text file handle for coverage output (opened for writing)
        finit: Text file handle for initialization output (opened for writing)
        k: List of instruction mnemonics
        covergroup_templates: Dictionary of template names to content
        tp: Test plan dictionary mapping instructions to coverpoints
        arch: Architecture name
        missing_templates: List to track missing templates (mutated in place)
        has_rv32: Whether to include RV32 instructions
        has_rv64: Whether to include RV64 instructions
    """
    for instr in k:
        cps = tp[instr]
        match32 = ("RV32" in cps) ^ (not has_rv32)
        match64 = ("RV64" in cps) ^ (not has_rv64)
        vectorwiden = (arch.startswith("Vx") or arch.startswith("Vls") or arch.startswith("Vf")) and (
            instr.startswith("vw") or instr.startswith("vfw") or (".w" in instr)
        )
        if match32 and match64:
            if vectorwiden:
                effew = get_effew(arch)
                f.write(
                    customize_template(covergroup_templates, "instruction_vector_widen", arch, instr, missing_templates, effew=effew)
                )
                finit.write(
                    customize_template(covergroup_templates, "init_vector_widen", arch, instr, missing_templates, effew=effew)
                )
            else:
                f.write(customize_template(covergroup_templates, "instruction", arch, instr, missing_templates))
                finit.write(customize_template(covergroup_templates, "init", arch, instr, missing_templates))
            for cp in cps:
                # Skip these initial columns
                if not (cp.startswith("sample_") or cp == "RV32" or cp == "RV64" or cp.startswith("EFFEW")):
                    if any(substring in cp for substring in SEW_DEPENDENT_CPS):
                        effew = get_effew(arch)
                        cp = cp + "_sew" + effew

                    if "sew_lte" in cp:
                        effew = get_effew(arch)
                        match = re.search(r"(\d+)$", cp)
                        if match:
                            num = int(match.group(1))
                            # only_sew8 should only be included if sew = 8
                            if int(effew) <= num:
                                cp = re.sub(r"_sew_lte_\d+", "", cp)
                                f.write(customize_template(covergroup_templates, cp, arch, instr, missing_templates))
                    else:
                        f.write(customize_template(covergroup_templates, cp, arch, instr, missing_templates))
            if vectorwiden:
                f.write(customize_template(covergroup_templates, "endgroup_vector_widen", arch, instr, missing_templates))
            else:
                f.write(customize_template(covergroup_templates, "endgroup", arch, instr, missing_templates))

def write_covergroup_sample_functions(
    f: TextIO,
    k: list[str],
    covergroup_templates: CovergroupTemplates,
    tp: dict[str, list[str]],
    arch: str,
    missing_templates: list[str],
    has_rv32: bool,
    has_rv64: bool,
) -> None:
    """Write covergroup sample functions for instructions.

    Args:
        f: Text file handle for output (opened for writing)
        k: List of instruction mnemonics
        covergroup_templates: Dictionary of template names to content
        tp: Test plan dictionary mapping instructions to coverpoints
        arch: Architecture name
        missing_templates: List to track missing templates (mutated in place)
        has_rv32: Whether to include RV32 instructions
        has_rv64: Whether to include RV64 instructions
    """
    for instr in k:
        cps = tp[instr]
        match32 = ("RV32" in cps) ^ (not has_rv32)
        match64 = ("RV64" in cps) ^ (not has_rv64)
        if match32 and match64:
            if arch.startswith("Vx") or arch.startswith("Vls") or arch.startswith("Vf"):
                if instr.startswith("vw") or instr.startswith("vfw") or (".w" in instr):
                    effew = get_effew(arch)
                    f.write(
                        customize_template(
                            covergroup_templates, "covergroup_sample_vector_widen", arch, instr, missing_templates, effew=effew
                        )
                    )
                else:
                    f.write(customize_template(covergroup_templates, "covergroup_sample_vector", arch, instr, missing_templates))
            elif arch != "E":  # E currently breaks coverage
                f.write(customize_template(covergroup_templates, "covergroup_sample", arch, instr, missing_templates))

def write_instruction_sample_function(
    f: TextIO,
    k: list[str],
    covergroup_templates: CovergroupTemplates,
    tp: dict[str, list[str]],
    arch: str,
    missing_templates: list[str],
    has_rv32: bool,
    has_rv64: bool,
) -> None:
    """Write instruction sample functions.

    Args:
        f: Text file handle for output (opened for writing)
        k: List of instruction mnemonics
        covergroup_templates: Dictionary of template names to content
        tp: Test plan dictionary mapping instructions to coverpoints
        arch: Architecture name
        missing_templates: List to track missing templates (mutated in place)
        has_rv32: Whether to include RV32 instructions
        has_rv64: Whether to include RV64 instructions
    """
    for instr in k:
        cps = tp[instr]
        match32 = ("RV32" in cps) ^ (not has_rv32)
        match64 = ("RV64" in cps) ^ (not has_rv64)
        if match32 and match64:
            for cp in cps:
                if cp.startswith("sample_"):
                    f.write(customize_template(covergroup_templates, cp, arch, instr, missing_templates))

def get_effew(arch: str) -> str:
    """Extract effective element width from architecture name.

    Args:
        arch: Architecture name (e.g., 'Vx32')

    Returns:
        Effective element width as a string (e.g., '32')

    Raises:
        ValueError: If architecture name doesn't contain an expected integer
    """
    match = re.search(r"(\d+)$", arch)
    if match:
        return match.group(1)
    raise ValueError(f"Arch does not contain an expected integer: '{arch}'")

def write_covergroups(
    test_plans: TestPlans,
    covergroup_templates: CovergroupTemplates,
    arch_sources: ArchSources,
    arch_verif: Path,
    missing_templates: list[str],
) -> None:
    """Generate covergroups for all instructions in each testplan.

    Iterates over the testplans and covergroup templates to generate the covergroups
    for all instructions in each testplan.

    Args:
        test_plans: Dictionary mapping architecture to instruction covergroups
        covergroup_templates: Dictionary of template names to content
        arch_sources: Dictionary mapping architecture to source category
        arch_verif: Root path of the architecture verification directory
        missing_templates: List to track missing templates (mutated in place)
    """
    covergroup_dir = arch_verif / "coverpoints"
    coverage_header_dir = covergroup_dir / "coverage"
    coverage_header_dir.mkdir(parents=True, exist_ok=True)

    with open(coverage_header_dir / "RISCV_instruction_sample.svh", "w") as fsample:
        fsample.write(customize_template(covergroup_templates, "instruction_sample_header", "NA", "NA", missing_templates))
        for arch, tp in test_plans.items():
            covergroup_sub_dir = arch_sources.get(arch, "unpriv")
            covergroup_out_dir = covergroup_dir / covergroup_sub_dir
            covergroup_out_dir.mkdir(parents=True, exist_ok=True)

            file = arch + "_coverage.svh"
            initfile = arch + "_coverage_init.svh"
            print("***** Writing " + file)

            vector = arch.startswith("Vx") or arch.startswith("Zv") or arch.startswith("Vls") or arch.startswith("Vf")
            effew = get_effew(arch) if vector else ""

            with open(covergroup_out_dir / file, "w") as f, open(covergroup_out_dir / initfile, "w") as finit:
                if vector:
                    f.write(customize_template(covergroup_templates, "header_vector", arch, "", missing_templates, effew=effew))
                else:
                    f.write(customize_template(covergroup_templates, "header", arch, "", missing_templates))
                finit.write(customize_template(covergroup_templates, "initheader", arch, "", missing_templates))

                k = sorted(tp.keys())
                if vector:
                    k = [instr for instr in k if f"EFFEW{effew}" in tp[instr]]

                write_instrs(f, finit, k, covergroup_templates, tp, arch, missing_templates, True, True)
                if any_exclusion("RV64", k, tp):
                    f.write(customize_template(covergroup_templates, "RV32", arch, "NA1", missing_templates))
                    finit.write(customize_template(covergroup_templates, "RV32", arch, "NA1", missing_templates))
                    write_instrs(f, finit, k, covergroup_templates, tp, arch, missing_templates, True, False)
                    f.write(customize_template(covergroup_templates, "end", arch, "NA1", missing_templates))
                    finit.write(customize_template(covergroup_templates, "end", arch, "NA1", missing_templates))
                if any_exclusion("RV32", k, tp):
                    f.write(customize_template(covergroup_templates, "RV64", arch, "NA2", missing_templates))
                    finit.write(customize_template(covergroup_templates, "RV64", arch, "NA2", missing_templates))
                    write_instrs(f, finit, k, covergroup_templates, tp, arch, missing_templates, False, True)
                    f.write(customize_template(covergroup_templates, "end", arch, "NA2", missing_templates))
                    finit.write(customize_template(covergroup_templates, "end", arch, "NA2", missing_templates))

                # Covergroup sample functions: also separate out generic and ones specific to RV32/RV64 with `ifdefs`
                if vector:
                    f.write(
                        customize_template(
                            covergroup_templates, "covergroup_sample_header_vector", arch, "NA3", missing_templates, effew=effew
                        )
                    )
                else:
                    f.write(customize_template(covergroup_templates, "covergroup_sample_header", arch, "NA3", missing_templates))
                write_covergroup_sample_functions(f, k, covergroup_templates, tp, arch, missing_templates, True, True)
                if any_exclusion("RV64", k, tp):
                    f.write(customize_template(covergroup_templates, "RV32", arch, "NA4", missing_templates))
                    write_covergroup_sample_functions(f, k, covergroup_templates, tp, arch, missing_templates, True, False)
                    f.write(customize_template(covergroup_templates, "end", arch, "NA4", missing_templates))
                if any_exclusion("RV32", k, tp):
                    f.write(customize_template(covergroup_templates, "RV64", arch, "NA5", missing_templates))
                    write_covergroup_sample_functions(f, k, covergroup_templates, tp, arch, missing_templates, False, True)
                    f.write(customize_template(covergroup_templates, "end", arch, "NA5", missing_templates))
                if vector:
                    f.write(
                        customize_template(covergroup_templates, "covergroup_sample_end_vector", arch, "NA3", missing_templates)
                    )
                else:
                    f.write(customize_template(covergroup_templates, "covergroup_sample_end", arch, "NA3", missing_templates))

                # Instruction sample function: also separate out generic and ones specific to RV32/RV64 with `ifdefs`
                write_instruction_sample_function(fsample, k, covergroup_templates, tp, arch, missing_templates, True, True)
                if any_exclusion("RV64", k, tp):
                    fsample.write(customize_template(covergroup_templates, "RV32", arch, "NA4", missing_templates))
                    write_instruction_sample_function(fsample, k, covergroup_templates, tp, arch, missing_templates, True, False)
                    fsample.write(customize_template(covergroup_templates, "end", arch, "NA4", missing_templates))
                if any_exclusion("RV32", k, tp):
                    fsample.write(customize_template(covergroup_templates, "RV64", arch, "NA5", missing_templates))
                    write_instruction_sample_function(fsample, k, covergroup_templates, tp, arch, missing_templates, False, True)
                    fsample.write(customize_template(covergroup_templates, "end", arch, "NA5", missing_templates))

        fsample.write(customize_template(covergroup_templates, "instruction_sample_end", "NA", "NA", missing_templates))

    # Create include files listing all the coverage groups to use in RISCV_coverage_base
    keys = sorted(test_plans.keys())
    # Add priv covergroups to list for initialization and sampling
    for priv_dir in ["priv", "rv32_priv", "rv64_priv"]:
        priv_path = covergroup_dir / priv_dir
        if priv_path.exists():
            keys.extend(f.stem.split("_")[0] for f in priv_path.iterdir() if f.name.endswith("_coverage.svh"))

    with open(coverage_header_dir / "RISCV_coverage_base_init.svh", "w") as f:
        for arch in keys:
            f.write(customize_template(covergroup_templates, "coverageinit", arch, "", missing_templates))

    with open(coverage_header_dir / "RISCV_coverage_base_sample.svh", "w") as f:
        for arch in keys:
            f.write(customize_template(covergroup_templates, "coveragesample", arch, "", missing_templates))



##################################
# Main Python Script
##################################


def main() -> None:
    """Main entry point for covergroup generation."""
    # Determine the architecture verification root directory
    script_path = Path(sys.argv[0]).resolve()
    arch_verif = script_path.parent.parent.parent

    # Keep list of missing templates to only print once
    missing_templates: list[str] = []

    # Read test plans and templates
    test_plans, arch_sources = read_testplans(arch_verif)
    covergroup_templates = read_covergroup_templates(arch_verif)

    # Generate covergroups
    write_covergroups(test_plans, covergroup_templates, arch_sources, arch_verif, missing_templates)


if __name__ == "__main__":
    main()
