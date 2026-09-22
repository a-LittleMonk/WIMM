"""OF zone schema. OF stays primarily on ZoneDrawer's native arena/center_zone/
grid handling, but expose a schema view for plugin parity."""


def build_schema(host):
    """Return a schema list reflecting the current OF zone state on `host`
    (an OpenFieldTab). Read-only mirror — the drawer keeps native state."""
    schema = []
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return schema
    if zd.arena:
        schema.append({
            "name": "arena",
            "type": "polygon",
            "geometry": list(zd.arena),
            "style": {"color": "#3CA0FF", "thickness": 2, "label_text": "Arena"},
            "editable": True,
            "editor_hint": {"n_corners": 4},
        })
    if zd.center_zone:
        schema.append({
            "name": "center_zone",
            "type": "polygon",
            "geometry": list(zd.center_zone),
            "style": {"color": "#3CDC64", "thickness": 2, "label_text": "Center Zone"},
            "editable": False,
        })
    if zd.calib_p1 and zd.calib_p2:
        schema.append({
            "name": "calib",
            "type": "line",
            "geometry": (zd.calib_p1, zd.calib_p2),
            "style": {"color": "#FFC800", "thickness": 2},
            "editable": True,
        })
    return schema
