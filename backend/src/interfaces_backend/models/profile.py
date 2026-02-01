"""Profile class/instance data models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProfileClassInfo(BaseModel):
    """Profile class summary."""

    id: str = Field(..., description="Profile class UUID")
    class_key: str = Field(..., description="Profile class key")
    version: int = Field(1, description="Profile class version")
    description: str = Field("", description="Profile class description")


class ProfileClassesResponse(BaseModel):
    classes: List[ProfileClassInfo] = Field(default_factory=list)
    total: int = Field(0)


class ProfileClassDetailResponse(BaseModel):
    profile_class: Dict[str, Any] = Field(..., description="Full profile class spec")


class ProfileClassCreateRequest(BaseModel):
    class_key: str = Field(..., description="Profile class key")
    version: int = Field(1, description="Profile class version")
    description: str = Field("", description="Profile class description")
    defaults: Dict[str, Any] = Field(default_factory=dict)
    profile: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProfileClassUpdateRequest(BaseModel):
    version: Optional[int] = None
    description: Optional[str] = None
    defaults: Optional[Dict[str, Any]] = None
    profile: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class ProfileInstanceModel(BaseModel):
    id: str = Field(..., description="Instance id")
    class_id: str = Field(..., description="Profile class UUID")
    class_key: str = Field(..., description="Profile class key")
    class_version: int = Field(1, description="Profile class version")
    name: str = Field("active", description="Instance name")
    variables: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    thumbnail_key: Optional[str] = Field(None, description="R2 key for profile thumbnail")
    is_active: bool = Field(False, description="Active instance")
    created_at: Optional[str] = Field(None, description="Created at")
    updated_at: Optional[str] = Field(None, description="Updated at")


class ProfileInstancesResponse(BaseModel):
    instances: List[ProfileInstanceModel] = Field(default_factory=list)
    total: int = Field(0)


class ProfileInstanceCreateRequest(BaseModel):
    class_id: str
    name: Optional[str] = "active"
    variables: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    thumbnail_key: Optional[str] = None
    activate: bool = True


class ProfileInstanceUpdateRequest(BaseModel):
    name: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    thumbnail_key: Optional[str] = None
    activate: bool = True


class ProfileInstanceResponse(BaseModel):
    instance: ProfileInstanceModel
    message: str = ""


class ProfileDeviceStatusCamera(BaseModel):
    name: str
    enabled: bool = True
    connected: bool = False
    topics: List[str] = Field(default_factory=list)


class ProfileDeviceStatusArm(BaseModel):
    name: str
    enabled: bool = True
    connected: bool = False


class ProfileInstanceStatusResponse(BaseModel):
    profile_id: Optional[str] = None
    profile_class_key: Optional[str] = None
    cameras: List[ProfileDeviceStatusCamera] = Field(default_factory=list)
    arms: List[ProfileDeviceStatusArm] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)


class VlaborStatusResponse(BaseModel):
    status: str = Field("unknown", description="running | stopped | unknown")
    service: str = Field("vlabor", description="compose service name")
    state: Optional[str] = None
    status_detail: Optional[str] = None
    running_for: Optional[str] = None
    created_at: Optional[str] = None
    container_id: Optional[str] = None
