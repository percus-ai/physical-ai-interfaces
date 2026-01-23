import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import streamlit as st


DEFAULT_METRIC_OPTIONS = ["成功", "失敗", "部分成功"]


def _backend_url() -> str:
    return os.environ.get("PHI_BACKEND_URL", "http://localhost:8000").rstrip("/")


def _api_request(method: str, path: str, **kwargs) -> Optional[Any]:
    url = f"{_backend_url()}{path}"
    try:
        response = httpx.request(method, url, timeout=20, **kwargs)
    except httpx.RequestError as exc:
        st.error(f"Backend request failed: {exc}")
        return None
    if response.status_code >= 400:
        detail: Any
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        st.error(f"API error {response.status_code}: {detail}")
        return None
    if response.status_code == 204:
        return None
    return response.json()


def _api_get(path: str, params: Optional[dict] = None) -> Optional[Any]:
    return _api_request("GET", path, params=params)


def _api_post(path: str, payload: dict) -> Optional[Any]:
    return _api_request("POST", path, json=payload)


def _api_patch(path: str, payload: dict) -> Optional[Any]:
    return _api_request("PATCH", path, json=payload)


def _api_put(path: str, payload: dict) -> Optional[Any]:
    return _api_request("PUT", path, json=payload)


def _api_delete(path: str) -> Optional[Any]:
    return _api_request("DELETE", path)


def _api_upload(path: str, files: List[tuple]) -> Optional[Any]:
    return _api_request("POST", path, files=files)


@st.cache_data(ttl=10)
def _load_models() -> List[dict]:
    data = _api_get("/api/storage/models") or {}
    return data.get("models", [])


@st.cache_data(ttl=10)
def _load_datasets() -> List[dict]:
    data = _api_get("/api/storage/datasets") or {}
    return data.get("datasets", [])


@st.cache_data(ttl=10)
def _load_environments() -> List[dict]:
    data = _api_get("/api/storage/environments") or {}
    return data.get("environments", [])


def _load_experiments() -> List[dict]:
    data = _api_get("/api/experiments") or {}
    return data.get("experiments", [])


def _load_evaluations(experiment_id: str) -> List[dict]:
    data = _api_get(f"/api/experiments/{experiment_id}/evaluations") or {}
    return data.get("evaluations", [])


def _load_analysis_blocks(experiment_id: str) -> List[dict]:
    data = _api_get(f"/api/experiments/{experiment_id}/analyses") or {}
    return data.get("analyses", [])


def _load_summary(experiment_id: str) -> dict:
    return _api_get(f"/api/experiments/{experiment_id}/evaluation_summary") or {}


def _get_query_param(key: str) -> Optional[str]:
    value = st.query_params.get(key)
    if isinstance(value, list):
        return value[0]
    if isinstance(value, str):
        return value
    return None


def _set_mode(mode: str, experiment_id: Optional[str] = None) -> None:
    st.session_state["mode"] = mode
    if experiment_id:
        st.session_state["experiment_id"] = experiment_id
    params = dict(st.query_params)
    params["mode"] = mode
    if experiment_id:
        params["experiment"] = experiment_id
    else:
        params.pop("experiment", None)
    st.query_params.clear()
    st.query_params.update(params)


def _metric_options_from_text(text: str) -> Optional[List[str]]:
    parts = [item.strip() for item in text.split(",") if item.strip()]
    return parts or None


def _metric_options_to_text(options: Optional[List[str]]) -> str:
    if not options:
        return ", ".join(DEFAULT_METRIC_OPTIONS)
    return ", ".join(options)


def _format_rates(summary: dict) -> str:
    rates = summary.get("rates") or {}
    if not rates:
        return "-"
    pairs = [f"{key}: {value:.1f}%" for key, value in rates.items()]
    return " | ".join(pairs)


def _render_list() -> None:
    st.subheader("実験一覧")
    if st.button("実験を作成", use_container_width=True):
        _set_mode("create")
        return

    experiments = _load_experiments()
    if not experiments:
        st.info("実験がありません。")
        return

    models = {m["id"]: m for m in _load_models()}
    envs = {e["id"]: e for e in _load_environments()}

    rows = []
    for exp in experiments:
        summary = _load_summary(exp["id"])
        rows.append(
            {
                "id": exp["id"],
                "name": exp.get("name", ""),
                "model": models.get(exp.get("model_id"), {}).get("name", exp.get("model_id")),
                "environment": envs.get(exp.get("environment_id"), {}).get(
                    "name", exp.get("environment_id")
                ),
                "evaluation_count": exp.get("evaluation_count", 0),
                "evaluations": summary.get("total", 0),
                "rates": _format_rates(summary),
            }
        )

    st.dataframe(rows, use_container_width=True)

    experiment_id = st.selectbox(
        "実験を選択",
        options=[row["id"] for row in rows],
        format_func=lambda x: f"{x} - {next(r['name'] for r in rows if r['id'] == x)}",
    )
    cols = st.columns(3)
    if cols[0].button("詳細を開く", use_container_width=True):
        _set_mode("detail", experiment_id)
    if cols[1].button("評価入力を開く", use_container_width=True):
        _set_mode("evaluations", experiment_id)
    if cols[2].button("考察入力を開く", use_container_width=True):
        _set_mode("analyses", experiment_id)


def _render_create() -> None:
    st.subheader("実験作成")
    models = _load_models()
    envs = _load_environments()

    if not models:
        st.warning("実験作成にはモデルが必要です。")
        if st.button("戻る"):
            _set_mode("list")
        return

    model_label = {m["id"]: m.get("name", m["id"]) for m in models}
    env_label = {e["id"]: e.get("name", e["id"]) for e in envs}

    default_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    with st.form("create_experiment_form"):
        model_id = st.selectbox("モデル", options=list(model_label.keys()), format_func=model_label.get)
        env_options = [None] + list(env_label.keys())
        environment_id = st.selectbox(
            "環境（任意）",
            options=env_options,
            format_func=lambda x: "未設定" if x is None else env_label.get(x, x),
        )
        name = st.text_input("実験名", value=default_name)
        purpose = st.text_area("実験目的", height=80)
        evaluation_count = st.number_input("評価回数", min_value=1, value=10, step=1)
        metric = st.text_input("評価指標", value="binary")
        metric_options_text = st.text_input(
            "評価候補（カンマ区切り）", value=", ".join(DEFAULT_METRIC_OPTIONS)
        )
        notes = st.text_area("備考", height=80)
        submitted = st.form_submit_button("作成", use_container_width=True)

    if submitted:
        payload = {
            "model_id": model_id,
            "environment_id": environment_id,
            "name": name,
            "purpose": purpose or None,
            "evaluation_count": int(evaluation_count),
            "metric": metric,
            "metric_options": _metric_options_from_text(metric_options_text),
            "notes": notes or None,
        }
        result = _api_post("/api/experiments", payload)
        if result:
            st.success("実験を作成しました。")
            _set_mode("detail", result["id"])

    if st.button("戻る"):
        _set_mode("list")


def _render_detail(experiment_id: str) -> None:
    exp = _api_get(f"/api/experiments/{experiment_id}")
    if not exp:
        if st.button("Back"):
            _set_mode("list")
        return

    models = {m["id"]: m for m in _load_models()}
    envs = {e["id"]: e for e in _load_environments()}
    datasets = {d["id"]: d for d in _load_datasets()}

    model = models.get(exp.get("model_id"))
    env = envs.get(exp.get("environment_id"))
    dataset = datasets.get(model.get("dataset_id")) if model else None

    st.subheader("実験詳細")
    with st.form("experiment_update_form"):
        name = st.text_input("実験名", value=exp.get("name", ""))
        purpose = st.text_area("実験目的", value=exp.get("purpose") or "", height=80)
        evaluation_count = st.number_input(
            "評価回数", min_value=1, value=int(exp.get("evaluation_count") or 1), step=1
        )
        metric = st.text_input("評価指標", value=exp.get("metric") or "binary")
        metric_options_text = st.text_input(
            "評価候補（カンマ区切り）",
            value=_metric_options_to_text(exp.get("metric_options")),
        )
        uploaded_files = st.file_uploader(
            "結果画像アップロード",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
        )
        existing_images = exp.get("result_image_files") or []
        st.caption("既存の画像キー:")
        st.code("\n".join(existing_images) if existing_images else "なし")
        result_image_files = existing_images
        notes = st.text_area("備考", value=exp.get("notes") or "", height=80)
        submitted = st.form_submit_button("更新", use_container_width=True)

    if submitted:
        if uploaded_files:
            files = [("files", (f.name, f.getvalue(), f.type)) for f in uploaded_files]
            upload = _api_upload(f"/api/experiments/{experiment_id}/uploads?scope=experiment", files)
            if upload and upload.get("keys"):
                result_image_files = list(result_image_files) + upload["keys"]

        payload = {
            "name": name,
            "purpose": purpose or None,
            "evaluation_count": int(evaluation_count),
            "metric": metric,
            "metric_options": _metric_options_from_text(metric_options_text),
            "result_image_files": result_image_files,
            "notes": notes or None,
        }
        result = _api_patch(f"/api/experiments/{experiment_id}", payload)
        if result:
            st.success("実験を更新しました。")

    st.markdown("---")
    st.subheader("参照情報（編集不可）")
    st.write("モデル:", model.get("name") if model else exp.get("model_id"))
    st.write("環境:", env.get("name") if env else exp.get("environment_id") or "未設定")
    if dataset:
        st.write("データセット:", dataset.get("name") or dataset.get("id"))

    if st.button("実験を削除", type="primary"):
        result = _api_delete(f"/api/experiments/{experiment_id}")
        if result:
            st.success("実験を削除しました。")
            _set_mode("list")

    cols = st.columns(2)
    if cols[0].button("一覧に戻る", use_container_width=True):
        _set_mode("list")
    if cols[1].button("評価入力を開く", use_container_width=True):
        _set_mode("evaluations", experiment_id)


def _render_evaluations(experiment_id: str) -> None:
    exp = _api_get(f"/api/experiments/{experiment_id}")
    if not exp:
        if st.button("Back"):
            _set_mode("list")
        return

    st.subheader("評価入力")
    existing = _load_evaluations(experiment_id)
    existing_map = {e["trial_index"]: e for e in existing}
    evaluation_count = int(exp.get("evaluation_count") or 0)
    metric_options = exp.get("metric_options") or DEFAULT_METRIC_OPTIONS

    with st.form("evaluations_form"):
        values: List[str] = []
        notes_list: List[str] = []
        for idx in range(1, evaluation_count + 1):
            row = existing_map.get(idx, {})
            current_value = row.get("value") or ""
            options = metric_options + ["その他"]
            default_index = options.index(current_value) if current_value in metric_options else len(options) - 1
            st.markdown(f"**試行 {idx}**")
            selection = st.selectbox(
                f"評価値（{idx}）",
                options=options,
                index=default_index,
                key=f"value_select_{experiment_id}_{idx}",
            )
            if selection == "その他":
                custom_value = st.text_input(
                    f"自由入力（{idx}）",
                    value=current_value if current_value not in metric_options else "",
                    key=f"value_custom_{experiment_id}_{idx}",
                )
                values.append(custom_value.strip())
            else:
                values.append(selection)
            note = st.text_input(
                f"備考（{idx}）",
                value=row.get("notes") or "",
                key=f"value_notes_{experiment_id}_{idx}",
            )
            notes_list.append(note)
            existing_images = row.get("image_files") or []
            st.caption("画像キー:")
            st.code("\n".join(existing_images) if existing_images else "なし")
            eval_uploads = st.file_uploader(
                f"評価画像アップロード（{idx}）",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                key=f"eval_upload_{experiment_id}_{idx}",
            )
            if eval_uploads:
                files = [("files", (f.name, f.getvalue(), f.type)) for f in eval_uploads]
                upload = _api_upload(
                    f"/api/experiments/{experiment_id}/uploads?scope=evaluation&trial_index={idx}",
                    files,
                )
                if upload and upload.get("keys"):
                    existing_images = list(existing_images) + upload["keys"]
            st.session_state[f"eval_images_{experiment_id}_{idx}"] = existing_images
            st.divider()
        submitted = st.form_submit_button("評価を保存", use_container_width=True)

    if submitted:
        image_files_list = [
            st.session_state.get(f"eval_images_{experiment_id}_{idx}", [])
            for idx in range(1, evaluation_count + 1)
        ]
        items = [
            {"value": value or "", "notes": note or None, "image_files": images}
            for value, note, images in zip(values, notes_list, image_files_list)
        ]
        result = _api_put(f"/api/experiments/{experiment_id}/evaluations", {"items": items})
        if result:
            st.success("評価を保存しました。")

    summary = _load_summary(experiment_id)
    st.markdown("### 集計")
    st.write("合計:", summary.get("total", 0))
    st.write("割合:", _format_rates(summary))

    cols = st.columns(2)
    if cols[0].button("一覧に戻る", use_container_width=True):
        _set_mode("list")
    if cols[1].button("考察入力を開く", use_container_width=True):
        _set_mode("analyses", experiment_id)


def _render_analyses(experiment_id: str) -> None:
    exp = _api_get(f"/api/experiments/{experiment_id}")
    if not exp:
        if st.button("Back"):
            _set_mode("list")
        return

    st.subheader("考察入力")
    key = f"analysis_blocks_{experiment_id}"
    if key not in st.session_state:
        st.session_state[key] = _load_analysis_blocks(experiment_id)

    if st.button("ブロック追加", use_container_width=True):
        st.session_state[key].append({})

    with st.form("analyses_form"):
        items: List[dict] = []
        for idx, block in enumerate(st.session_state[key], start=1):
            with st.expander(f"ブロック {idx}", expanded=True):
                name = st.text_input(
                    f"考察名（{idx}）",
                    value=block.get("name") or "",
                    key=f"analysis_name_{experiment_id}_{idx}",
                )
                purpose = st.text_input(
                    f"考察目的（{idx}）",
                    value=block.get("purpose") or "",
                    key=f"analysis_purpose_{experiment_id}_{idx}",
                )
                notes = st.text_area(
                    f"考察内容（{idx}）",
                    value=block.get("notes") or "",
                    height=80,
                    key=f"analysis_notes_{experiment_id}_{idx}",
                )
                images = st.text_area(
                    f"画像キー（{idx}）",
                    value="\n".join(block.get("image_files") or []),
                    height=80,
                    key=f"analysis_images_{experiment_id}_{idx}",
                )
                items.append(
                    {
                        "name": name or None,
                        "purpose": purpose or None,
                        "notes": notes or None,
                        "image_files": [line for line in images.splitlines() if line.strip()],
                    }
                )
        submitted = st.form_submit_button("考察を保存", use_container_width=True)

    if submitted:
        result = _api_put(f"/api/experiments/{experiment_id}/analyses", {"items": items})
        if result:
            st.success("考察を保存しました。")
            st.session_state[key] = _load_analysis_blocks(experiment_id)

    cols = st.columns(2)
    if cols[0].button("一覧に戻る", use_container_width=True):
        _set_mode("list")
    if cols[1].button("評価入力を開く", use_container_width=True):
        _set_mode("evaluations", experiment_id)


def main() -> None:
    st.set_page_config(page_title="Experiments", layout="wide")
    st.title("実験管理")

    query_mode = _get_query_param("mode")
    query_experiment = _get_query_param("experiment")

    if query_mode:
        st.session_state["mode"] = query_mode
    if query_experiment:
        st.session_state["experiment_id"] = query_experiment

    mode = st.session_state.get("mode", "list")
    experiment_id = st.session_state.get("experiment_id")

    if mode == "create":
        _render_create()
        return
    if mode == "detail" and experiment_id:
        _render_detail(experiment_id)
        return
    if mode == "evaluations" and experiment_id:
        _render_evaluations(experiment_id)
        return
    if mode == "analyses" and experiment_id:
        _render_analyses(experiment_id)
        return

    _render_list()


if __name__ == "__main__":
    main()
