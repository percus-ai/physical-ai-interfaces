from interfaces_backend.services.vlabor_profiles import (
    extract_camera_specs,
    extract_recorder_topic_suffixes,
)


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


def test_extract_recorder_topic_suffixes_resolves_from_snapshot() -> None:
    snapshot = {
        "profile": {
            "teleop": {
                "topic_mappings": [
                    {"dst": "/follower_left/joint_ctrl_single"},
                    {"dst": "/follower_right/joint_ctrl_single"},
                ]
            },
            "lerobot": {
                "follower_left": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                },
                "follower_right": {
                    "namespace": "follower_right",
                    "topic": "/follower_right/joint_states_single",
                },
            },
        }
    }

    assert extract_recorder_topic_suffixes(
        snapshot,
        arm_namespaces=["follower_left", "follower_right"],
    ) == {
        "state_topic_suffix": "joint_states_single",
        "action_topic_suffix": "joint_ctrl_single",
    }


def test_extract_recorder_topic_suffixes_returns_empty_when_mixed_action_suffixes() -> None:
    snapshot = {
        "profile": {
            "teleop": {
                "topic_mappings": [
                    {"dst": "/follower_left/joint_ctrl_single"},
                    {"dst": "/follower_right/ik/joint_angles"},
                ]
            },
            "lerobot": {
                "follower_left": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                },
                "follower_right": {
                    "namespace": "follower_right",
                    "topic": "/follower_right/joint_states_single",
                },
            },
        }
    }

    assert extract_recorder_topic_suffixes(
        snapshot,
        arm_namespaces=["follower_left", "follower_right"],
    ) == {
        "state_topic_suffix": "joint_states_single",
    }
