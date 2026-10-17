from pathlib import Path

from app.shared.config import Settings
from app.shared.paths import PROJECT_ROOT


def test_default_dataset_path_is_inside_project_and_independent_of_cwd(monkeypatch, tmp_path):
    project = PROJECT_ROOT
    monkeypatch.chdir(tmp_path)
    default = Path(Settings.model_fields["normalized_data_dir"].default)
    assert default.is_absolute()
    assert default == project / "data" / "normalized"
