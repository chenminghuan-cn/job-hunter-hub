"""状态机定义：唯一真相源，前端通过 /api/meta 读取，外放接口据此校验。

每个实体一套 {状态: {label, color, terminal?, transitions: [...]}}。
新增状态只需在这里加一项，页面下拉、接口校验自动跟着变。
"""


def _m(states):
    return states


JOB = _m({
    "new":         {"label": "新发现", "color": "blue",      "transitions": ["shortlisted", "rejected"]},
    "shortlisted": {"label": "已入选", "color": "geekblue",  "transitions": ["applied", "rejected"]},
    "applied":     {"label": "已投递", "color": "processing", "transitions": ["interviewing", "rejected"]},
    "interviewing": {"label": "面试中", "color": "orange",   "transitions": ["offer", "rejected"]},
    "offer":       {"label": "已获 Offer", "color": "gold",  "transitions": ["accepted", "rejected"]},
    "accepted":    {"label": "已接受", "color": "green",     "transitions": ["archived"]},
    "rejected":    {"label": "已放弃", "color": "default",   "transitions": ["archived"]},
    "archived":    {"label": "已归档", "color": "default",   "transitions": ["new"]},
})

COMPANY = _m({
    "new":         {"label": "新线索", "color": "blue",     "transitions": ["researching", "target", "blacklisted"]},
    "researching": {"label": "调研中", "color": "processing", "transitions": ["target", "blacklisted"]},
    "target":      {"label": "目标公司", "color": "green",  "transitions": ["archived", "blacklisted"]},
    "blacklisted": {"label": "已拉黑", "color": "red",      "transitions": ["new"]},
    "archived":    {"label": "已归档", "color": "default",  "transitions": ["new"]},
})

CONTACT = _m({
    "new":       {"label": "待联系", "color": "blue",      "transitions": ["contacted"]},
    "contacted": {"label": "已联系", "color": "processing", "transitions": ["replied", "cold"]},
    "replied":   {"label": "已回复", "color": "cyan",      "transitions": ["following", "closed", "cold"]},
    "following": {"label": "跟进中", "color": "orange",    "transitions": ["closed", "cold"]},
    "cold":      {"label": "已沉默", "color": "default",   "transitions": ["contacted"]},
    "closed":    {"label": "已结束", "color": "default",   "transitions": ["following"]},
})

CHANNEL = _m({
    "active":       {"label": "采集中", "color": "green",
                     "transitions": ["need_verify", "login_expired", "degraded", "paused", "disabled"]},
    "need_verify":  {"label": "待人工验证", "color": "red", "human": True,
                     "transitions": ["active", "paused", "disabled"]},
    "login_expired": {"label": "登录失效", "color": "volcano", "human": True,
                     "transitions": ["active", "paused", "disabled"]},
    "degraded":     {"label": "受限（限流/风控）", "color": "orange",
                     "transitions": ["active", "need_verify", "paused", "disabled"]},
    "paused":       {"label": "已暂停", "color": "default",
                     "transitions": ["active", "disabled"]},
    "disabled":     {"label": "已停用", "color": "default",
                     "transitions": ["active", "paused"]},
})

MACHINES = {"job": JOB, "company": COMPANY, "contact": CONTACT, "channel": CHANNEL}


class TransitionError(ValueError):
    pass


def check(entity: str, current: str, target: str):
    m = MACHINES[entity]
    if target not in m:
        raise TransitionError(f"{entity} 无状态 {target}")
    if target == current:
        return target
    allowed = m.get(current, {}).get("transitions", [])
    if target not in allowed:
        raise TransitionError(
            f"{entity} 不允许 {current} -> {target}，可选：{allowed or '无（终态）'}"
        )
    return target


def meta():
    return {
        m: {
            "states": [
                {"value": k, "label": v["label"], "color": v["color"],
                 "next": v["transitions"], "human": bool(v.get("human"))}
                for k, v in states.items()
            ],
            "initial": next(iter(states)),
        }
        for m, states in MACHINES.items()
    }
