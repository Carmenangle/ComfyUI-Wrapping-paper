from pathlib import Path

from theme_asset_pipeline import main_for_manifest


if __name__ == "__main__":
    main_for_manifest(Path(__file__).with_name("theme_assets") / "green.json")
