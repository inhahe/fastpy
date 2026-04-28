"""
Optimization analysis report for the fastpy compiler.

Produces a human-readable (and machine-readable) report explaining which
parts of a Python program prevent specific fast-path optimizations, and
roughly how much each costs.

Usage:
    python -m compiler --analyze program.py

The report is generated as a side-effect of normal compilation — every
optimization decision point in CodeGen records a finding when analyze
mode is active.  After codegen completes, build_report() reads the
accumulated findings and post-analysis state to produce the final report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


# ── Severity constants ──────────────────────────────────────────────────

CRITICAL = "CRITICAL"   # Bridge fallback — CPython interpreter, ~100-1000×
HIGH     = "HIGH"       # Bare-ABI disabled — shadow stack, no LLVM loop opts
MEDIUM   = "MEDIUM"     # Boxed attrs, generic list access, missed hoisting
LOW      = "LOW"        # Monomorphization, unresolved types, code-size effects

_SEVERITY_ORDER = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}

# ── Impact estimate strings ─────────────────────────────────────────────

IMPACT_BRIDGE = "~100-1000× slower (executed by CPython interpreter, not native code)"
IMPACT_BARE_ABI_MODULE = "~2-5× loop overhead (shadow stack + line tracking on all module code)"
IMPACT_BARE_ABI_FUNC = "~2-5× loop overhead (shadow stack + line tracking per call/return)"
IMPACT_BOXED_ATTR = "~1-3 ns per access (tag check + memory indirection vs native load)"
IMPACT_INIT_ONLY_MISSED = "prevents LLVM loop hoisting (attribute re-loaded every iteration)"
IMPACT_GENERIC_LIST = "~3-5 ns per access (function call vs inline memory load)"
IMPACT_MONOMORPHIZED = "extra code size; may prevent cross-call inlining"
IMPACT_UNRESOLVED_TYPE = "may cascade: prevents bare-ABI, monomorphization, or typed attrs"


# ── Data structures ─────────────────────────────────────────────────────

@dataclass
class OptimizationFinding:
    """A single optimization decision that affects performance."""
    severity: str           # CRITICAL / HIGH / MEDIUM / LOW
    category: str           # machine-readable category tag
    line: int | None        # source line number (None if whole-scope)
    scope: str              # e.g. "module", "function:foo", "class:Point"
    construct: str          # the code construct, e.g. "eval(expr)"
    optimization_missed: str  # what could have been faster
    reason: str             # why the optimization couldn't apply
    impact_estimate: str    # human-readable impact string
    suggestion: str = ""    # optional user-facing advice

    @property
    def sort_key(self) -> tuple:
        return (_SEVERITY_ORDER.get(self.severity, 9),
                self.line or 0, self.scope)


@dataclass
class ScopeStats:
    """Optimization statistics for a single scope (function, class, module)."""
    name: str
    kind: str                  # "module", "function", "class"
    bare_abi: bool = False
    total_attrs: int = 0       # for classes: total attribute count
    native_attrs: int = 0      # unboxed native-typed attrs
    boxed_attrs: int = 0       # generic FpyValue attrs
    init_only_attrs: int = 0   # attrs with invariant.load potential
    monomorphized: bool = False


@dataclass
class ReportSummary:
    """Aggregate statistics across the entire report."""
    total_findings: int = 0
    by_severity: dict[str, int] = field(default_factory=dict)
    bridge_fallback_count: int = 0
    bare_abi_functions: int = 0
    total_functions: int = 0
    total_classes: int = 0
    native_attr_ratio: str = ""    # e.g. "18/24 (75%)"
    monomorphized_functions: int = 0


@dataclass
class OptimizationReport:
    """Complete optimization analysis for a compiled program."""
    findings: list[OptimizationFinding] = field(default_factory=list)
    scope_stats: dict[str, ScopeStats] = field(default_factory=dict)
    summary: ReportSummary = field(default_factory=ReportSummary)

    def to_text(self, max_findings: int = 0) -> str:
        """Render the report as human-readable text.

        Args:
            max_findings: Maximum findings to show per severity tier.
                0 = unlimited.
        """
        lines: list[str] = []
        s = self.summary

        lines.append("=" * 52)
        lines.append("  fastpy Optimization Analysis")
        lines.append("=" * 52)
        lines.append("")

        # ── Summary ──
        lines.append("Summary:")
        if s.total_functions:
            pct = (s.bare_abi_functions / s.total_functions * 100
                   if s.total_functions else 0)
            lines.append(f"  Functions: {s.total_functions} total, "
                         f"{s.bare_abi_functions} bare-ABI ({pct:.0f}%)")
        if s.total_classes:
            lines.append(f"  Classes: {s.total_classes}")
        if s.native_attr_ratio:
            lines.append(f"  Attribute storage: {s.native_attr_ratio}")
        if s.monomorphized_functions:
            lines.append(f"  Monomorphized functions: "
                         f"{s.monomorphized_functions}")
        if s.bridge_fallback_count:
            lines.append(f"  Bridge fallbacks: {s.bridge_fallback_count}")

        sev_parts = []
        for sev in (CRITICAL, HIGH, MEDIUM, LOW):
            count = s.by_severity.get(sev, 0)
            if count:
                sev_parts.append(f"{count} {sev}")
        if sev_parts:
            lines.append(f"  Findings: {', '.join(sev_parts)}")
        elif not self.findings:
            lines.append("  No optimization findings — all fast paths active.")

        # ── Findings by severity ──
        sorted_findings = sorted(self.findings, key=lambda f: f.sort_key)

        for sev in (CRITICAL, HIGH, MEDIUM, LOW):
            tier = [f for f in sorted_findings if f.severity == sev]
            if not tier:
                continue
            lines.append("")
            lines.append(f"--- {sev} ---")
            lines.append("")

            shown = tier[:max_findings] if max_findings else tier
            for f in shown:
                loc = f"line {f.line}" if f.line else "scope-level"
                lines.append(f"  [{loc}] {f.scope}")
                lines.append(f"    {f.optimization_missed}: {f.construct}")
                lines.append(f"    Impact: {f.impact_estimate}")
                lines.append(f"    Reason: {f.reason}")
                if f.suggestion:
                    lines.append(f"    Suggestion: {f.suggestion}")
                lines.append("")

            if max_findings and len(tier) > max_findings:
                lines.append(f"  ... and {len(tier) - max_findings} more "
                             f"{sev} findings\n")

        # ── Per-class details ──
        class_stats = [ss for ss in self.scope_stats.values()
                       if ss.kind == "class"]
        if class_stats:
            lines.append("--- Class Attribute Breakdown ---")
            lines.append("")
            for cs in class_stats:
                if cs.total_attrs == 0:
                    continue
                pct = (cs.native_attrs / cs.total_attrs * 100
                       if cs.total_attrs else 0)
                lines.append(
                    f"  {cs.name}: {cs.native_attrs}/{cs.total_attrs} "
                    f"native ({pct:.0f}%), "
                    f"{cs.init_only_attrs} init-only (hoistable)")
                if cs.boxed_attrs:
                    lines.append(
                        f"    {cs.boxed_attrs} attrs stored as generic "
                        f"FpyValue (tag check on every access)")
            lines.append("")

        return "\n".join(lines)

    def to_json(self) -> dict:
        """Serialize the report to a JSON-compatible dict."""
        return {
            "summary": {
                "total_findings": self.summary.total_findings,
                "by_severity": self.summary.by_severity,
                "bridge_fallback_count": self.summary.bridge_fallback_count,
                "bare_abi_functions": self.summary.bare_abi_functions,
                "total_functions": self.summary.total_functions,
                "total_classes": self.summary.total_classes,
                "native_attr_ratio": self.summary.native_attr_ratio,
                "monomorphized_functions": self.summary.monomorphized_functions,
            },
            "findings": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "line": f.line,
                    "scope": f.scope,
                    "construct": f.construct,
                    "optimization_missed": f.optimization_missed,
                    "reason": f.reason,
                    "impact_estimate": f.impact_estimate,
                    "suggestion": f.suggestion,
                }
                for f in sorted(self.findings, key=lambda f: f.sort_key)
            ],
            "scope_stats": {
                name: {
                    "kind": ss.kind,
                    "bare_abi": ss.bare_abi,
                    "total_attrs": ss.total_attrs,
                    "native_attrs": ss.native_attrs,
                    "boxed_attrs": ss.boxed_attrs,
                    "init_only_attrs": ss.init_only_attrs,
                    "monomorphized": ss.monomorphized,
                }
                for name, ss in self.scope_stats.items()
            },
        }

    def to_json_str(self, indent: int = 2) -> str:
        return json.dumps(self.to_json(), indent=indent)


# ── Report builder ──────────────────────────────────────────────────────

def build_report(codegen) -> OptimizationReport:
    """Build an OptimizationReport from a CodeGen instance after generate().

    Reads the accumulated _opt_findings list and post-analysis data
    structures (class attr slots, float/string/bool attrs, init-only attrs,
    monomorphization info, function metadata).
    """
    report = OptimizationReport()
    report.findings = list(getattr(codegen, '_opt_findings', []))

    # ── Scope stats: functions ──
    bare_count = 0
    total_funcs = 0
    mono_count = 0
    monomorphized = getattr(codegen, '_monomorphized', {})

    for name, finfo in getattr(codegen, '_user_functions', {}).items():
        # Skip monomorphized variant aliases — they share a FuncInfo and
        # would be double-counted.
        if '__' in name and any(name.startswith(f"{base}__")
                                for base in monomorphized):
            continue
        total_funcs += 1
        is_bare = getattr(finfo, 'uses_bare_abi', False)
        if is_bare:
            bare_count += 1
        is_mono = name in monomorphized
        if is_mono:
            mono_count += 1
        report.scope_stats[f"function:{name}"] = ScopeStats(
            name=name, kind="function",
            bare_abi=is_bare,
            monomorphized=is_mono,
        )

    # ── Scope stats: classes ──
    total_native = 0
    total_all_attrs = 0

    class_attr_slots = getattr(codegen, '_class_attr_slots', {})
    float_attrs = getattr(codegen, '_per_class_float_attrs', {})
    string_attrs = getattr(codegen, '_per_class_string_attrs', {})
    bool_attrs = getattr(codegen, '_per_class_bool_attrs', {})
    container_attrs = getattr(codegen, '_class_container_attrs', {})
    obj_attr_types = getattr(codegen, '_class_obj_attr_types', {})
    init_only = getattr(codegen, '_class_init_only_attrs', {})

    for cls_name, slots in class_attr_slots.items():
        total = len(slots)
        if total == 0:
            continue

        typed_set = set()
        typed_set |= float_attrs.get(cls_name, set())
        typed_set |= string_attrs.get(cls_name, set())
        typed_set |= bool_attrs.get(cls_name, set())
        list_a, dict_a = container_attrs.get(cls_name, (set(), set()))
        typed_set |= list_a
        typed_set |= dict_a
        typed_set |= set(obj_attr_types.get(cls_name, {}).keys())

        native = len(typed_set & set(slots.keys()))
        boxed = total - native
        io_count = len(init_only.get(cls_name, set()) & set(slots.keys()))

        total_native += native
        total_all_attrs += total

        report.scope_stats[f"class:{cls_name}"] = ScopeStats(
            name=cls_name, kind="class",
            total_attrs=total,
            native_attrs=native,
            boxed_attrs=boxed,
            init_only_attrs=io_count,
        )

    # ── Summary ──
    s = report.summary
    s.total_findings = len(report.findings)
    s.by_severity = {}
    for f in report.findings:
        s.by_severity[f.severity] = s.by_severity.get(f.severity, 0) + 1
    s.bridge_fallback_count = s.by_severity.get(CRITICAL, 0)
    s.bare_abi_functions = bare_count
    s.total_functions = total_funcs
    s.total_classes = len(class_attr_slots)
    s.monomorphized_functions = mono_count
    if total_all_attrs:
        pct = total_native / total_all_attrs * 100
        s.native_attr_ratio = (f"{total_native}/{total_all_attrs} "
                               f"({pct:.0f}%)")

    return report
