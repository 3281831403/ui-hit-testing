# UI 命中测试修复（ui-hit-testing）

UI 换成自定义命中测试后，旋转按钮点不中、弹窗还挡不住下层点击：to_local 的逆变换用了 +θ 而不是 −θ，旋转后的按钮命中区域整体偏到镜像位置；to_local 的缩放用了乘法而不是除法，2× 缩放节点的可点区域反而只剩一半；in_rect 用开区间，点恰好压在边界上被判为不命中；hit_test 按节点插入顺序返回而没按 z 序，弹窗被下层按钮抢先命中；hit_test 只返回第一个命中并忽略 pass_through，穿透链直接断掉；clip_children 把子矩形与父裁剪矩形求并集，滚动容器外的内容仍然可点；z_order 用不稳定排序，同 z 节点每次的先后都可能变化；penetrate 递归时不检查子节点 visible，隐藏节点仍被算进命中；validate_node 不检查父子循环，环状节点会一路递归到栈溢出；hit_batch 跨帧复用变换矩阵，第二帧沿用第一帧的 matrix，整帧点歪。hit/tester.py 是核心，tests/test_tester.py 15个红。要修的是：上述 10 处隐蔽缺陷。

> 难点是变换与顺序：逆矩阵、闭区间、稳定 z 序、裁剪交集。

## 运行方式

在仓库根目录执行：

```powershell
cd D:\gsb-20261119\ui-hit-testing
python -m pytest tests -q
```

初始状态必须恰好收集到 15 个测试，并且全部失败、没有 collection / import / syntax error，输出尾部形如：

```text
15 failed in 0.12s
```

环境为 Python 3 与 pytest，离线、无外部依赖、不使用随机数。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 游戏、图形与多媒体 |
| 子方向 | 图形渲染 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

## 实现要求

`hit/tester.py` 中的 8 个函数目前全部是 `raise NotImplementedError` 的桩，需要按各自 docstring 的契约实现：世界/局部坐标变换、闭区间矩形包含、按 z 序的递归命中、父裁剪矩形求交集、稳定 z 排序、穿透查询、节点合法性校验，以及逐帧独立的批量命中。

节点是普通 `dict`，包含 `path`、`pos`、`size`、`rot`、`scale`、`z`、`visible`、`pass_through`、`children`，并可选 `clip`。角度单位为弧度，逆时针为正；`size` 定义局部矩形 `(0, 0, w, h)`；所有浮点比较容差为 `1e-9`。只允许使用标准库（`math`）和 pytest。

## 测试不可修改

`tests/test_tester.py` 是验收契约，**不可修改**。不要通过改测试、跳过测试、放宽断言或添加 pytest 配置来制造绿色；应实现 `hit/tester.py` 使原始 15 个测试通过。
