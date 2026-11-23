"""Novel Object Location — NOR's setup and nose-based scoring with two
identical objects, one of which has been moved since training. Roles are
Stationary / Moved instead of Familiar / Novel; every result is named
accordingly. Everything else is NOR's code (family "nor")."""
from experiments.nor.experiment import NORExperiment
from experiments.nor import zones as nor_zones

_RENAME = {
    "familiar_time_s": "stationary_time_s",
    "novel_time_s": "moved_time_s",
    "preference_pct_novel": "preference_pct_moved",
}
_ROLE_VALUE = {"familiar": "stationary", "novel": "moved"}


def _rename_list(keys):
    return [_RENAME.get(k, k) for k in keys]


class NOLExperiment(NORExperiment):
    name = "Novel Object Location"
    key = "nol"
    family = "nor"
    results_title = "NOL"
    role_labels = {
        nor_zones.ROLE_NONE: "—",
        nor_zones.ROLE_FAMILIAR: "Stationary",
        nor_zones.ROLE_NOVEL: "Moved",
    }

    def compute_metrics(self, results, settings, fps, px_per_cm):
        metrics, raw_df, bin_df = super().compute_metrics(
            results, settings, fps, px_per_cm)
        out = {}
        for k, v in metrics.items():
            if k.endswith("_role") and v in _ROLE_VALUE:
                v = _ROLE_VALUE[v]
            out[_RENAME.get(k, k)] = v
        return out, raw_df, bin_df

    def summary_table_keys(self, metrics):
        return _rename_list(super().summary_table_keys(metrics))

    def export_columns(self):
        return _rename_list(super().export_columns())

    def batch_schema(self):
        return [(sec, _rename_list(cols)) for sec, cols in super().batch_schema()]

    def zone_bar_data(self, host):
        spec = super().zone_bar_data(host)
        if not spec:
            return spec
        m = getattr(host, "metrics", None) or {}
        labels = []
        for obj_id, default in (("object_a", "Object A"), ("object_b", "Object B")):
            name = m.get(f"{obj_id}_name") or default
            role = m.get(f"{obj_id}_role")
            labels.append(f"{name} ({role})" if role in ("stationary", "moved") else name)
        return (labels,) + tuple(spec[1:])

    def populate_results_tab(self, host, metrics):
        # Reuse NOR's table with renamed rows.
        m = dict(metrics or {})
        m["familiar_time_s"] = m.get("stationary_time_s")
        m["novel_time_s"] = m.get("moved_time_s")
        m["preference_pct_novel"] = m.get("preference_pct_moved")
        super().populate_results_tab(host, m)
        t = getattr(host, "_nor_table", None)
        if t is None:
            return
        swap = {"Familiar time (s)": "Stationary time (s)",
                "Novel time (s)": "Moved time (s)",
                "Preference for Novel (%)": "Preference for Moved (%)"}
        for r in range(t.rowCount()):
            it = t.item(r, 0)
            if it is not None and it.text() in swap:
                it.setText(swap[it.text()])
