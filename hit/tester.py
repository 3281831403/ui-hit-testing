"""自定义 UI 命中测试的核心实现。

节点是普通 ``dict``，字段约定如下（所有坐标均使用同一套二维坐标系，
``rot`` 为正时逆时针旋转，单位为弧度）::

    {
        "path": "root/panel/button",   # 全局唯一路径，也是命中结果
        "pos": (x, y),                 # 节点原点在父坐标系中的位置
        "size": (w, h),                # 节点局部矩形 (0, 0, w, h)
        "rot": 0.0,                    # 绕节点原点旋转
        "scale": (1.0, 1.0),           # 局部坐标缩放
        "z": 0,                        # 同级/全局绘制序，越大越靠上
        "visible": True,               # 自身及整棵子树是否参与命中
        "pass_through": False,         # 是否允许点击继续落到下层
        "children": [],                # 子节点列表
        "clip": (x, y, w, h),          # 可选，父局部坐标中的裁剪矩形
    }

节点的 ``pos`` / ``rot`` / ``scale`` 是相对于父节点的局部变换；顶层节点的
父坐标系就是世界坐标系。所有浮点比较容差为 1e-9。
"""

from __future__ import annotations

import math

EPS = 1e-9

# 字段缺失时的默认值（与 validate_node 的契约一致）。
_DEFAULT_POS = (0.0, 0.0)
_DEFAULT_SIZE = (0.0, 0.0)
_DEFAULT_ROT = 0.0
_DEFAULT_SCALE = (1.0, 1.0)
_DEFAULT_Z = 0


def to_local(point, node):
    """把点从节点父坐标系变换到节点局部坐标系。

    正向变换（局部 -> 父坐标系）为::

        parent = pos + R(rot) @ (scale * local)

    其中 ``R(rot)`` 是逆时针旋转矩阵。因此逆变换必须先用 ``R(-rot)``
    旋转，再逐分量除以 ``scale``；旋转方向与缩放方向都不能弄反。

    参数:
        point: ``(x, y)``，位于节点父坐标系（顶层节点即世界坐标系）。
        node: 含 ``pos``、``rot``、``scale`` 的节点字典。

    返回:
        ``(lx, ly)``，节点局部坐标中的浮点二元组。

    容差:
        数值比较使用 1e-9。
    """
    px, py = node.get("pos", _DEFAULT_POS)
    rot = node.get("rot", _DEFAULT_ROT)
    sx, sy = node.get("scale", _DEFAULT_SCALE)

    # 先撤销平移。
    dx = point[0] - px
    dy = point[1] - py

    # 再撤销旋转：逆矩阵是 R(-rot)。
    # R(-t) = [[cos t, sin t], [-sin t, cos t]]
    cos_r = math.cos(rot)
    sin_r = math.sin(rot)
    rx = cos_r * dx + sin_r * dy
    ry = -sin_r * dx + cos_r * dy

    # 最后撤销缩放：正向是乘法，逆向必须是除法。
    return rx / sx, ry / sy


def in_rect(local, size):
    """判断局部点是否落在矩形 ``[0, w] x [0, h]`` 内。

    采用闭区间语义：点恰好位于左/右/上/下边界时必须命中。
    为吸收浮点误差，坐标在边界外不超过 1e-9 时仍算命中。

    参数:
        local: ``(x, y)`` 局部点。
        size: ``(w, h)`` 矩形尺寸，``w`` 与 ``h`` 应非负。

    返回:
        ``bool``。
    """
    x, y = local
    w, h = size
    return bool(-EPS <= x <= w + EPS and -EPS <= y <= h + EPS)


def _collect_hits(nodes, parent_point):
    """先序遍历节点树，返回所有几何命中的 ``(z, 发现序, path, pass_through)``。

    ``parent_point`` 是父坐标系中的查询点（顶层调用即世界坐标）。
    隐藏节点及其整棵子树直接跳过。发现序用于同 z 时的稳定排序。
    """
    hits = []
    counter = 0

    def walk(children, point):
        nonlocal counter
        for node in children:
            if not node.get("visible", True):
                # 隐藏节点连同整棵子树一起排除，不再递归。
                continue

            local_point = to_local(point, node)
            size = node.get("size", _DEFAULT_SIZE)
            if in_rect(local_point, size):
                hits.append(
                    (
                        node.get("z", _DEFAULT_Z),
                        counter,
                        node["path"],
                        bool(node.get("pass_through", False)),
                    )
                )
                counter += 1

            # 无论自身是否命中，子节点仍可能命中（子矩形可以超出父矩形）。
            walk(node.get("children", []), local_point)

    walk(nodes, parent_point)
    # z 从大到小；同 z 保持先序发现顺序（稳定排序）。
    hits.sort(key=lambda item: (-item[0], item[1]))
    return hits


def hit_test(nodes, point):
    """递归命中测试，返回从最上层开始的一段命中链。

    规则:
        1. 先序遍历节点树，复合祖先与自身的平移/旋转/缩放；隐藏节点
           及其整棵子树都不参与命中。
        2. 用 ``to_local`` 与 ``in_rect`` 判断每个可见节点的局部矩形。
           本函数只做几何命中，不应用 ``clip``（裁剪请使用
           ``clip_children``）。
        3. 命中按 ``z`` 从大到小排序；``z`` 相同时保持先序发现顺序
           （稳定排序）。也就是最上层在前。
        4. 从排序后的第一个命中开始收集路径；遇到第一个
           ``pass_through`` 为假（或缺省）的节点时，把它计入结果并停止。
           因此返回的是"顶层 + 连续穿透层 + 遮挡层"，而不是只返回一个
           节点，也不是忽略 ``pass_through``。
        5. 没有命中时返回空列表。

    参数:
        nodes: 顶层节点列表。
        point: 世界坐标 ``(x, y)``。

    返回:
        ``list[str]``，节点 ``path`` 按最上层在前排列。

    容差:
        变换与边界比较均使用 1e-9。
    """
    ordered = _collect_hits(nodes, point)
    result = []
    for _z, _index, path, is_pass_through in ordered:
        result.append(path)
        if not is_pass_through:
            # 遮挡层计入结果后立即停止，后面的层级被挡住。
            break
    return result


def clip_children(node):
    """计算父节点每个直接子节点被父裁剪矩形截取后的有效区域。

    父裁剪矩形取 ``node["clip"]``，格式为父局部坐标中的
    ``(x, y, w, h)``；若没有该字段，则退化为父节点自身矩形
    ``(0, 0, size[0], size[1])``。

    对每个直接子节点，先把它在父局部坐标中的矩形按子节点的
    ``pos`` / ``rot`` / ``scale`` / ``size`` 展开成轴对齐包围盒，再与
    父裁剪矩形求**交集**（不是并集）。只有宽和高都大于 1e-9 的交集
    才会返回；刚好擦边、交集面积为零的子节点忽略。

    返回项按子节点原插入顺序排列，格式为::

        (child["path"], (x0, y0, x1, y1))

    其中矩形用父局部坐标下的左上/右下边界表示。``visible`` 不参与
    本函数的纯几何裁剪计算。

    参数:
        node: 含 ``children``，可选 ``clip`` 的父节点字典。

    返回:
        ``list[tuple[str, tuple[float, float, float, float]]]``。

    容差:
        交集尺寸判断使用 1e-9。
    """
    if "clip" in node:
        clip_x, clip_y, clip_w, clip_h = node["clip"]
    else:
        clip_x, clip_y = 0.0, 0.0
        clip_w, clip_h = node.get("size", _DEFAULT_SIZE)
    clip_x1 = clip_x + clip_w
    clip_y1 = clip_y + clip_h

    result = []
    for child in node.get("children", []):
        px, py = child.get("pos", _DEFAULT_POS)
        rot = child.get("rot", _DEFAULT_ROT)
        sx, sy = child.get("scale", _DEFAULT_SCALE)
        w, h = child.get("size", _DEFAULT_SIZE)
        cos_r = math.cos(rot)
        sin_r = math.sin(rot)

        # 局部矩形四个角经正向变换 parent = pos + R(rot) @ (scale * local)
        # 映射到父局部坐标，取轴对齐包围盒。
        xs = []
        ys = []
        for lx, ly in ((0.0, 0.0), (w, 0.0), (0.0, h), (w, h)):
            scaled_x = sx * lx
            scaled_y = sy * ly
            xs.append(px + cos_r * scaled_x - sin_r * scaled_y)
            ys.append(py + sin_r * scaled_x + cos_r * scaled_y)
        box_x0, box_x1 = min(xs), max(xs)
        box_y0, box_y1 = min(ys), max(ys)

        # 与父裁剪矩形求交集。
        inter_x0 = max(clip_x, box_x0)
        inter_y0 = max(clip_y, box_y0)
        inter_x1 = min(clip_x1, box_x1)
        inter_y1 = min(clip_y1, box_y1)

        if inter_x1 - inter_x0 > EPS and inter_y1 - inter_y0 > EPS:
            result.append((child["path"], (inter_x0, inter_y0, inter_x1, inter_y1)))

    return result


def z_order(nodes):
    """返回稳定的 z 序节点列表。

    按 ``z`` 从大到小排序（最上层在前）；``z`` 相同的节点保持输入
    列表中的先后顺序。必须返回新列表，不能原地修改 ``nodes``。

    参数:
        nodes: 同一层的节点字典列表。

    返回:
        ``list``，元素仍是原节点字典。
    """
    # Python 的 sorted 是稳定排序：key 相等时保持原顺序，且返回新列表。
    return sorted(nodes, key=lambda item: -item.get("z", _DEFAULT_Z))


def penetrate(nodes, point, pass_through):
    """穿透模式命中查询。

    与 ``hit_test`` 使用相同的可见性、递归变换、几何包含与 z 序规则，
    但由 ``pass_through`` 决定返回多少层:

    * ``True``：返回全部可见命中，按最上层在前；忽略节点自身的
      ``pass_through`` 标志，也忽略遮挡层，用于调试/事件分发。
    * ``False``：只返回最上层的一个命中（无命中则空列表）。

    隐藏节点以及隐藏祖先下面的整棵子树都必须过滤掉；隐藏子节点不能
    因为父节点可见就被命中。

    参数:
        nodes: 顶层节点列表。
        point: 世界坐标 ``(x, y)``。
        pass_through: 是否返回全部命中层。

    返回:
        ``list[str]``。

    容差:
        变换与边界比较均使用 1e-9。
    """
    ordered = _collect_hits(nodes, point)
    paths = [path for _z, _index, path, _pt in ordered]
    if pass_through:
        return paths
    # 非穿透模式只保留最上层的一个命中。
    return paths[:1]


def validate_node(node):
    """检查节点树中的缩放、NaN 与父子循环。

    字段缺失时按以下默认值处理：``pos=(0, 0)``、``size=(0, 0)``、
    ``rot=0.0``、``scale=(1, 1)``、``z=0``、``children=[]``。

    检查项与错误码:
        * ``"nan"``：``pos``、``size``、``rot``、``scale``、``z`` 中任一
          数值为 NaN。
        * ``"zero_scale"``：``scale`` 任一分量恰好为 0。
        * ``"cycle"``：沿 ``children`` 递归时回到当前递归栈中的祖先节点
          （即父子引用成环）。必须检测并停止，不能无限递归。

    返回去重后的错误码列表，顺序固定为
    ``["nan", "zero_scale", "cycle"]`` 中实际命中的子序列。
    普通 DAG（同一个子节点被两个不同父节点共享）不是环，不报
    ``"cycle"``。

    参数:
        node: 根节点字典。

    返回:
        ``list[str]``。
    """
    found = set()
    # 递归栈上的节点 id：只有回到栈中祖先才算环；DAG 共享不报环。
    on_stack = set()

    def walk(current):
        current_id = id(current)
        if current_id in on_stack:
            found.add("cycle")
            # 环已确认，剪枝终止，避免无限递归。
            return
        on_stack.add(current_id)

        pos = current.get("pos", _DEFAULT_POS)
        size = current.get("size", _DEFAULT_SIZE)
        rot = current.get("rot", _DEFAULT_ROT)
        scale = current.get("scale", _DEFAULT_SCALE)
        z = current.get("z", _DEFAULT_Z)

        numeric_values = [pos[0], pos[1], size[0], size[1], rot, scale[0], scale[1], z]
        if any(isinstance(value, float) and math.isnan(value) for value in numeric_values):
            found.add("nan")

        if scale[0] == 0 or scale[1] == 0:
            found.add("zero_scale")

        for child in current.get("children", []):
            walk(child)

        on_stack.discard(current_id)

    walk(node)

    return [code for code in ("nan", "zero_scale", "cycle") if code in found]


def hit_batch(frames, config):
    """批量执行多帧命中测试，每帧完全独立。

    ``frames`` 是帧列表，每帧为::

        {"nodes": [节点...], "point": (x, y)}

    ``config`` 支持:
        * ``"mode"``: ``"hit"``（默认，调用 ``hit_test``）或
          ``"penetrate"``（调用 ``penetrate``）。
        * ``"pass_through"``: 仅 ``mode="penetrate"`` 时使用，默认
          ``True``。

    返回 ``{帧下标: [path, ...]}``，键为从 0 开始的整数。每帧都必须
    依据自己的节点变换与点重新计算，不能跨帧复用上一帧的变换矩阵或
    局部坐标缓存。

    参数:
        frames: 帧字典列表。
        config: 配置字典，可为空字典。

    返回:
        ``dict[int, list[str]]``。
    """
    mode = config.get("mode", "hit")
    results = {}
    for index, frame in enumerate(frames):
        # 每帧独立调用，不保留任何跨帧的矩阵/坐标缓存。
        if mode == "penetrate":
            pass_through = config.get("pass_through", True)
            results[index] = penetrate(frame["nodes"], frame["point"], pass_through)
        else:
            results[index] = hit_test(frame["nodes"], frame["point"])
    return results
