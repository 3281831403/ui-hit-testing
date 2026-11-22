"""hit/tester.py 的验收测试。本文件是只读契约，不得修改。"""

from __future__ import annotations

import math

import pytest

from hit.tester import (
    clip_children,
    hit_batch,
    hit_test,
    in_rect,
    penetrate,
    to_local,
    validate_node,
    z_order,
)

EPS = 1e-9


def _node(
    path,
    *,
    pos=(0.0, 0.0),
    size=(10.0, 10.0),
    rot=0.0,
    scale=(1.0, 1.0),
    z=0,
    visible=True,
    pass_through=False,
    clip=None,
    children=None,
):
    node = {
        "path": path,
        "pos": (float(pos[0]), float(pos[1])),
        "size": (float(size[0]), float(size[1])),
        "rot": float(rot),
        "scale": (float(scale[0]), float(scale[1])),
        "z": z,
        "visible": visible,
        "pass_through": pass_through,
        "children": list(children or []),
    }
    if clip is not None:
        node["clip"] = (float(clip[0]), float(clip[1]), float(clip[2]), float(clip[3]))
    return node


def test_to_local_inverts_rotation():
    """缺陷 1：逆变换必须用 -rot，而不是 +rot。"""
    node = _node("dial", pos=(100.0, 50.0), size=(40.0, 20.0), rot=math.pi / 2.0)
    # local (30, 5) 经 90 度旋转后，世界坐标为 (100 - 5, 50 + 30)。
    local = to_local((95.0, 80.0), node)
    assert local == pytest.approx((30.0, 5.0), abs=EPS)


def test_to_local_divides_by_scale():
    """缺陷 2：世界 -> 局部要除以缩放，缩放 2x 不能反而缩半。"""
    node = _node("scaled", pos=(0.0, 0.0), size=(10.0, 10.0), scale=(2.0, 0.5))
    local = to_local((6.0, 2.0), node)
    assert local == pytest.approx((3.0, 4.0), abs=EPS)


def test_in_rect_includes_boundary_points():
    """缺陷 3：闭区间，四条边与两个角都算命中。"""
    size = (10.0, 20.0)
    assert in_rect((0.0, 0.0), size) is True
    assert in_rect((10.0, 20.0), size) is True
    assert in_rect((0.0, 20.0), size) is True
    assert in_rect((10.0, 0.0), size) is True
    assert in_rect((-1e-6, 5.0), size) is False
    assert in_rect((10.0 + 1e-6, 5.0), size) is False


def test_hit_test_orders_hits_by_z_not_insertion_order():
    """缺陷 4：hit_test 必须按 z 排序，不能按插入顺序返回。"""
    back = _node("back", size=(100.0, 100.0), z=1)
    top = _node("top", size=(100.0, 100.0), z=9, pass_through=True)
    middle = _node("middle", size=(100.0, 100.0), z=5, pass_through=True)
    # 插入顺序刻意是 back, top, middle；正确结果必须从 z=9 开始。
    assert hit_test([back, top, middle], (50.0, 50.0)) == ["top", "middle", "back"]


def test_hit_test_honours_pass_through_chain():
    """缺陷 5：不能首命中即返回，也不能忽略 pass_through。"""
    front = _node("front", size=(100.0, 100.0), z=20, pass_through=True)
    back = _node("back", size=(100.0, 100.0), z=10, pass_through=False)
    assert hit_test([front, back], (20.0, 20.0)) == ["front", "back"]

    modal = _node("modal", size=(100.0, 100.0), z=30, pass_through=False)
    assert hit_test([front, back, modal], (20.0, 20.0)) == ["modal"]


def test_clip_children_intersects_parent_clip():
    """缺陷 6：子矩形与父裁剪矩形必须求交集，不能求并集。"""
    a = _node("panel/a", pos=(0.0, 0.0), size=(30.0, 30.0))
    b = _node("panel/b", pos=(80.0, 40.0), size=(40.0, 40.0))
    c = _node("panel/c", pos=(0.0, 100.0), size=(40.0, 20.0))
    panel = _node(
        "panel",
        size=(200.0, 200.0),
        clip=(10.0, 10.0, 100.0, 50.0),
        children=[a, b, c],
    )

    assert clip_children(panel) == [
        ("panel/a", (10.0, 10.0, 30.0, 30.0)),
        ("panel/b", (80.0, 40.0, 110.0, 60.0)),
    ]


def test_z_order_is_stable_for_equal_z():
    """缺陷 7：同 z 必须保持插入顺序，且不能原地排序。"""
    nodes = [
        _node("a", z=2),
        _node("b", z=1),
        _node("c", z=2),
        _node("d", z=3),
        _node("e", z=2),
    ]
    assert [n["path"] for n in z_order(nodes)] == ["d", "a", "c", "e", "b"]
    assert [n["path"] for n in nodes] == ["a", "b", "c", "d", "e"]


def test_penetrate_skips_hidden_subtrees():
    """缺陷 8：递归时必须检查子节点 visible，隐藏分支整棵跳过。"""
    inner = _node("root/hidden/inner", size=(50.0, 50.0), z=101)
    hidden = _node(
        "root/hidden",
        size=(50.0, 50.0),
        z=100,
        visible=False,
        children=[inner],
    )
    shown = _node("root/visible", size=(50.0, 50.0), z=0)
    root = _node("root", size=(0.0, 0.0), children=[hidden, shown])

    assert penetrate([root], (10.0, 10.0), True) == ["root/visible"]


def test_validate_node_detects_zero_scale_nan_and_cycles():
    """缺陷 9：除缩放与 NaN 外，还必须检测父子循环并终止。"""
    assert validate_node(_node("zero", scale=(0.0, 1.0))) == ["zero_scale"]
    assert validate_node(_node("nan", rot=float("nan"))) == ["nan"]

    a = _node("a")
    b = _node("b")
    a["children"] = [b]
    b["children"] = [a]
    assert validate_node(a) == ["cycle"]


def test_hit_batch_does_not_reuse_first_frame_transform():
    """缺陷 10：第二帧必须用自己的矩阵，不能沿用第一帧。"""
    first = _node("btn", pos=(0.0, 0.0), size=(10.0, 10.0))
    second = _node("btn", pos=(100.0, 50.0), size=(10.0, 10.0), rot=math.pi / 2.0)
    frames = [
        {"nodes": [first], "point": (5.0, 5.0)},
        # local (5, 5) 旋转 90 度并平移后是 (95, 55)。
        {"nodes": [second], "point": (95.0, 55.0)},
    ]
    assert hit_batch(frames, {}) == {0: ["btn"], 1: ["btn"]}


def test_to_local_round_trip_with_translation_rotation_scale():
    """额外 1：平移/旋转/缩放组合的逆变换往返误差小于 1e-9。"""
    node = _node(
        "card",
        pos=(17.0, -9.0),
        size=(100.0, 100.0),
        rot=0.83,
        scale=(2.5, 0.4),
    )
    lx, ly = 3.2, 6.7
    cos_r, sin_r = math.cos(0.83), math.sin(0.83)
    wx = 17.0 + cos_r * 2.5 * lx - sin_r * 0.4 * ly
    wy = -9.0 + sin_r * 2.5 * lx + cos_r * 0.4 * ly

    assert to_local((wx, wy), node) == pytest.approx((lx, ly), abs=EPS)


def test_hit_test_accepts_exact_rectangle_boundary():
    """额外 2：点恰好落在节点矩形边界时也要命中。"""
    node = _node("slot", pos=(10.0, 20.0), size=(30.0, 40.0))
    assert hit_test([node], (10.0, 20.0)) == ["slot"]
    assert hit_test([node], (40.0, 60.0)) == ["slot"]
    assert hit_test([node], (40.0 + 1e-6, 60.0)) == []


def test_overlapping_nodes_report_topmost_first():
    """额外 3：多个重叠节点必须按 z 从上到下返回。"""
    panel = _node("panel", size=(200.0, 200.0), z=1, pass_through=True)
    button = _node(
        "panel/button",
        pos=(5.0, 5.0),
        size=(20.0, 20.0),
        z=9,
        pass_through=True,
    )
    overlay = _node("overlay", size=(200.0, 200.0), z=5, pass_through=True)
    panel["children"] = [button]

    assert hit_test([panel, overlay], (10.0, 10.0)) == [
        "panel/button",
        "overlay",
        "panel",
    ]


def test_penetrate_returns_all_hits_and_filters_hidden():
    """额外 4：穿透模式返回全部命中，同时过滤隐藏节点。"""
    backdrop = _node("backdrop", size=(200.0, 200.0), z=0)
    dialog = _node("dialog", size=(200.0, 200.0), z=10)
    ghost = _node("ghost", size=(200.0, 200.0), z=20, visible=False)

    assert penetrate([backdrop, dialog, ghost], (50.0, 50.0), True) == [
        "dialog",
        "backdrop",
    ]
    assert penetrate([backdrop, dialog, ghost], (50.0, 50.0), False) == ["dialog"]


def test_hit_batch_matches_per_frame_hit_test():
    """额外 5：批量两帧的结果必须与逐帧单独命中完全一致。"""
    frames = [
        {"nodes": [_node("left", pos=(0.0, 0.0))], "point": (5.0, 5.0)},
        {"nodes": [_node("right", pos=(100.0, 0.0))], "point": (105.0, 5.0)},
    ]
    batch = hit_batch(frames, {"mode": "hit"})
    individual = {
        index: hit_test(frame["nodes"], frame["point"])
        for index, frame in enumerate(frames)
    }

    assert batch == individual
    assert batch == {0: ["left"], 1: ["right"]}
