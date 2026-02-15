from interfaces_backend.services.vlabor_profiles import extract_camera_specs


def test_extract_camera_specs_uses_lerobot_cameras_only() -> None:
    snapshot = {
        "profile": {
            "actions": [
                {
                    "type": "include",
                    "package": "fv_camera",
                    "args": {"node_name": "fallback_camera"},
                    "enabled": True,
                }
            ]
        }
    }

    assert extract_camera_specs(snapshot) == []


def test_extract_camera_specs_resolves_lerobot_camera_fields() -> None:
    snapshot = {
        "profile": {
            "variables": {
                "camera_topic": "/top_camera/image_raw/compressed",
                "camera_enabled": "true",
            },
            "lerobot": {
                "cameras": [
                    {
                        "name": "cam_top",
                        "source": "top_camera",
                        "topic": "${camera_topic}",
                        "enabled": "${camera_enabled}",
                    },
                    {
                        "name": "cam_disabled",
                        "source": "depth_camera",
                        "topic": "/depth_camera/hha/compressed",
                        "enabled": False,
                    },
                ]
            },
        }
    }

    assert extract_camera_specs(snapshot) == [
        {
            "name": "cam_top",
            "source": "top_camera",
            "topic": "/top_camera/image_raw/compressed",
            "enabled": True,
            "package": "lerobot",
        },
        {
            "name": "cam_disabled",
            "source": "depth_camera",
            "topic": "/depth_camera/hha/compressed",
            "enabled": False,
            "package": "lerobot",
        },
    ]
