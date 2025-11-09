import os
import yaml
from jinja2 import Template
from app.manage import load_config, render_template

def test_load_config_reads_yaml(tmp_campaign_dir):
    cfg_path = tmp_campaign_dir / "campaign_config.yaml"
    cfg = yaml.safe_load(open(cfg_path))
    assert "from_email" in cfg
    assert isinstance(cfg["daily_send_limit"], int)

def test_render_template_inserts_variables(tmp_campaign_dir):
    tpl_path = tmp_campaign_dir / "template.html"
    html = render_template(tpl_path, {
        "first_name": "Mario",
        "email": "mario@example.com",
        "tracking_pixel_url": "https://tracker/pixel"
    })
    assert "Mario" in html
    assert "mario@example.com" in html
    assert "https://tracker/pixel" in html
