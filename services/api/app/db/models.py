# Model registry - import all models here to ensure SQLAlchemy relationships work
# This file must be imported early in the application lifecycle

from app.db.base import Base  # noqa: F401
from app.modules.agent_intents.models import AgentIntent  # noqa: F401
from app.modules.devices.models import Device  # noqa: F401
from app.modules.devices.pairing import PairingCode  # noqa: F401
from app.modules.libraries.models import Library  # noqa: F401
from app.modules.orgs.models import Org  # noqa: F401
from app.modules.people.models import DriveNicknameRegistry, PeopleClusterLabel, PeopleExcludePreference  # noqa: F401
from app.modules.profiles.models import LibraryProfile  # noqa: F401
from app.modules.shorts.models import SavedShort  # noqa: F401
from app.modules.drive.models import DriveConnection, DriveFile, DriveSecret  # noqa: F401
from app.modules.ingest.models import IdempotencyKey  # noqa: F401
from app.modules.users.models import User  # noqa: F401
from app.modules.basket.models import SceneBasket, SceneBasketItem  # noqa: F401
from app.modules.export.models import ExportRecord  # noqa: F401
from app.modules.search.models import SearchEvent  # noqa: F401
from app.modules.youtube.models import YouTubeChannel, YouTubeVideo  # noqa: F401
from app.modules.shorts_render.models import ShortsRenderJob  # noqa: F401
from app.modules.blur.models import BlurJob  # noqa: F401
from app.modules.scene_overrides.models import SceneOverride  # noqa: F401
from app.modules.videos.reprocess_models import SceneReprocessJob  # noqa: F401
from app.modules.video_summary.models import VideoSummary  # noqa: F401
