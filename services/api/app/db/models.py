# Model registry - import all models here to ensure SQLAlchemy relationships work
# This file must be imported early in the application lifecycle

from app.db.base import Base  # noqa: F401

# Import all models to register them with SQLAlchemy
from app.modules.orgs.models import Org  # noqa: F401
from app.modules.users.models import User  # noqa: F401
from app.modules.libraries.models import Library  # noqa: F401
from app.modules.profiles.models import LibraryProfile  # noqa: F401
from app.modules.devices.models import Device  # noqa: F401
from app.modules.people.models import DriveNicknameRegistry, PeopleClusterLabel  # noqa: F401
