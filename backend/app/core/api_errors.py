from dataclasses import dataclass, field


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    field_errors: list[dict[str, str]] = field(default_factory=list)
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

