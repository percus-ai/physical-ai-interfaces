"""HuggingFace Hub integration service."""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from interfaces_backend.models.storage import (
    DatasetMetadata,
    DatasetType,
    DataSource,
    DataStatus,
    HuggingFaceInfo,
    ModelConfig,
    ModelMetadata,
    ModelType,
    SyncInfo,
)
from interfaces_backend.services.storage.hash import compute_directory_hash, compute_directory_size
from interfaces_backend.services.storage.manifest import ManifestManager

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_id_to_local_id(repo_id: str) -> str:
    """Convert HuggingFace repo_id to local ID format."""
    return repo_id.replace("/", "--")


class HuggingFaceService:
    """Service for HuggingFace Hub integration."""

    def __init__(self, manifest_manager: ManifestManager):
        """Initialize HuggingFace service.

        Args:
            manifest_manager: The manifest manager instance
        """
        self.manifest = manifest_manager

    # --- Dataset Operations ---

    def import_dataset(
        self,
        repo_id: str,
        force: bool = False,
    ) -> Optional[DatasetMetadata]:
        """Import dataset from HuggingFace Hub.

        Args:
            repo_id: HuggingFace repo ID (e.g., "lerobot/pusht")
            force: Overwrite existing if present

        Returns:
            DatasetMetadata if successful
        """
        try:
            from huggingface_hub import snapshot_download
            from percus_ai.storage.hub import ensure_hf_token
        except ImportError:
            logger.error("huggingface_hub or percus_ai not available")
            return None

        ensure_hf_token()

        local_id = _repo_id_to_local_id(repo_id)
        existing = self.manifest.get_dataset(local_id)

        if existing and not force:
            logger.info(f"Dataset already exists: {local_id}")
            return existing

        local_path = self.manifest.get_dataset_path(local_id, DataSource.HUGGINGFACE)

        if local_path.exists() and force:
            shutil.rmtree(local_path)

        logger.info(f"Downloading dataset: {repo_id}")
        local_path.mkdir(parents=True, exist_ok=True)

        try:
            snapshot_download(
                repo_id=repo_id,
                repo_type="dataset",
                local_dir=str(local_path),
                local_dir_use_symlinks=False,
            )
        except Exception as e:
            logger.error(f"Failed to download dataset {repo_id}: {e}")
            if local_path.exists():
                shutil.rmtree(local_path)
            return None

        now = _now_iso()
        metadata = DatasetMetadata(
            id=local_id,
            name=repo_id.split("/")[-1],
            source=DataSource.HUGGINGFACE,
            status=DataStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            sync=SyncInfo(
                hash=compute_directory_hash(local_path),
                size_bytes=compute_directory_size(local_path),
                last_synced_at=now,
            ),
            dataset_type=DatasetType.HUGGINGFACE,
            huggingface=HuggingFaceInfo(
                repo_id=repo_id,
                downloaded_at=now,
            ),
        )

        self.manifest.register_dataset(metadata)
        logger.info(f"Imported dataset: {local_id}")
        return metadata

    def publish_dataset(
        self,
        dataset_id: str,
        repo_id: str,
        private: bool = False,
        commit_message: Optional[str] = None,
    ) -> Optional[str]:
        """Publish dataset to HuggingFace Hub.

        Args:
            dataset_id: Local dataset ID
            repo_id: Target HuggingFace repo ID
            private: Create private repository
            commit_message: Commit message

        Returns:
            Repository URL if successful
        """
        try:
            from huggingface_hub import HfApi, upload_folder
            from percus_ai.storage.hub import ensure_hf_token
        except ImportError:
            logger.error("huggingface_hub or percus_ai not available")
            return None

        ensure_hf_token()

        metadata = self.manifest.get_dataset(dataset_id)
        if not metadata:
            logger.error(f"Dataset not found: {dataset_id}")
            return None

        entry = self.manifest.manifest.datasets.get(dataset_id)
        if not entry:
            return None

        local_path = self.manifest.base_path / entry.path
        if not local_path.exists():
            logger.error(f"Dataset path not found: {local_path}")
            return None

        logger.info(f"Publishing dataset {dataset_id} to {repo_id}")

        try:
            api = HfApi()
            api.create_repo(
                repo_id=repo_id,
                repo_type="dataset",
                exist_ok=True,
                private=private,
            )

            if commit_message is None:
                commit_message = f"Upload dataset: {metadata.name}"

            upload_folder(
                folder_path=str(local_path),
                repo_id=repo_id,
                repo_type="dataset",
                commit_message=commit_message,
            )

            repo_url = f"https://huggingface.co/datasets/{repo_id}"
            logger.info(f"Published dataset to: {repo_url}")
            return repo_url
        except Exception as e:
            logger.error(f"Failed to publish dataset: {e}")
            return None

    # --- Model Operations ---

    def import_model(
        self,
        repo_id: str,
        force: bool = False,
    ) -> Optional[ModelMetadata]:
        """Import model from HuggingFace Hub.

        Args:
            repo_id: HuggingFace repo ID
            force: Overwrite existing if present

        Returns:
            ModelMetadata if successful
        """
        try:
            from percus_ai.storage.hub import download_model, ensure_hf_token, get_local_model_info
        except ImportError:
            logger.error("percus_ai.storage.hub not available")
            return None

        ensure_hf_token()

        local_id = _repo_id_to_local_id(repo_id)
        existing = self.manifest.get_model(local_id)

        if existing and not force:
            logger.info(f"Model already exists: {local_id}")
            return existing

        local_path = self.manifest.get_model_path(local_id, DataSource.HUGGINGFACE)

        if local_path.exists() and force:
            shutil.rmtree(local_path)

        logger.info(f"Downloading model: {repo_id}")

        try:
            download_model(
                repo_id=repo_id,
                output_dir=local_path,
                force=force,
            )
        except Exception as e:
            logger.error(f"Failed to download model {repo_id}: {e}")
            return None

        model_info = get_local_model_info(local_path)
        policy_type = model_info.policy_type if model_info else "unknown"

        now = _now_iso()
        metadata = ModelMetadata(
            id=local_id,
            name=repo_id.split("/")[-1],
            source=DataSource.HUGGINGFACE,
            status=DataStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            sync=SyncInfo(
                hash=compute_directory_hash(local_path),
                size_bytes=compute_directory_size(local_path),
                last_synced_at=now,
            ),
            model_type=ModelType.HUGGINGFACE,
            policy_type=policy_type,
            huggingface=HuggingFaceInfo(
                repo_id=repo_id,
                downloaded_at=now,
            ),
            config=ModelConfig(
                input_features=model_info.input_features if model_info else {},
                output_features=model_info.output_features if model_info else {},
            ),
        )

        self.manifest.register_model(metadata)
        logger.info(f"Imported model: {local_id}")
        return metadata

    def publish_model(
        self,
        model_id: str,
        repo_id: str,
        private: bool = False,
        commit_message: Optional[str] = None,
    ) -> Optional[str]:
        """Publish model to HuggingFace Hub.

        Args:
            model_id: Local model ID
            repo_id: Target HuggingFace repo ID
            private: Create private repository
            commit_message: Commit message

        Returns:
            Repository URL if successful
        """
        try:
            from percus_ai.storage.hub import ensure_hf_token, upload_model
        except ImportError:
            logger.error("percus_ai.storage.hub not available")
            return None

        ensure_hf_token()

        metadata = self.manifest.get_model(model_id)
        if not metadata:
            logger.error(f"Model not found: {model_id}")
            return None

        entry = self.manifest.manifest.models.get(model_id)
        if not entry:
            return None

        local_path = self.manifest.base_path / entry.path
        if not local_path.exists():
            logger.error(f"Model path not found: {local_path}")
            return None

        logger.info(f"Publishing model {model_id} to {repo_id}")

        try:
            repo_url = upload_model(
                local_path=local_path,
                repo_id=repo_id,
                private=private,
                commit_message=commit_message,
            )
            logger.info(f"Published model to: {repo_url}")
            return repo_url
        except Exception as e:
            logger.error(f"Failed to publish model: {e}")
            return None

    # --- Search ---

    def search_models(self, query: str, limit: int = 20) -> List[Dict]:
        """Search models on HuggingFace Hub.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of model info dictionaries
        """
        try:
            from percus_ai.storage.hub import search_hub_models
            return search_hub_models(query, limit)
        except ImportError:
            logger.error("percus_ai.storage.hub not available")
            return []

    def search_datasets(self, query: str, limit: int = 20) -> List[Dict]:
        """Search datasets on HuggingFace Hub.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of dataset info dictionaries
        """
        try:
            from huggingface_hub import list_datasets
            from percus_ai.storage.hub import ensure_hf_token
        except ImportError:
            logger.error("huggingface_hub not available")
            return []

        ensure_hf_token()

        results = []
        for ds in list_datasets(search=query, limit=limit):
            results.append({
                "id": ds.id,
                "downloads": getattr(ds, "downloads", 0),
                "likes": getattr(ds, "likes", 0),
                "created_at": str(getattr(ds, "created_at", "")),
            })

        return results
