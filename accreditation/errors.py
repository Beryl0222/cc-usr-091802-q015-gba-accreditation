"""领域异常。"""


class DomainError(Exception):
    """领域操作被拒绝。"""


class UnknownEntityError(DomainError):
    """引用了不存在的实体。"""


class NotEligibleError(DomainError):
    """当前通行结论不允许签发凭证。"""


class PermissionDeniedError(DomainError):
    """该角色无权访问此资源。"""
