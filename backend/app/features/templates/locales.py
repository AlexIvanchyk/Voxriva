from typing import Annotated

from pydantic import AfterValidator, StringConstraints

Locale = Annotated[
    str,
    StringConstraints(
        min_length=2, max_length=35, pattern="^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$"
    ),
    AfterValidator(str.lower),
]
