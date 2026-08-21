from __future__ import annotations

from elyon_agent.run import enroll_once


def test_enroll_once_with_existing_state(api, agent, agent_settings, enrolled):
    """--enroll-once avec state déjà présent : pas de wizard, message, sortie."""
    from elyon_agent.state import DeviceState

    _, _, device_id, token = enrolled
    DeviceState(device_id=device_id, token=token).save(agent_settings.state_file)

    output: list[str] = []
    enroll_once(agent, agent_settings, input_fn=lambda _: "", print_fn=output.append)

    assert any("enrôlement OK" in line for line in output)
    assert any(device_id in line for line in output)


def test_enroll_once_first_run_runs_wizard(api, agent, agent_settings, enrolled):
    """--enroll-once sans state : le wizard s'exécute avec un nouveau code."""
    from elyon_agent.state import DeviceState

    _, site_id, _, _ = enrolled
    # Nouveau code d'enrôlement pour un second device.
    token = api.post(f"/api/enroll/tokens?site_id={site_id}&ttl_seconds=600",
                     headers={"X-CSRF-Token": api.cookies.get("elyon_csrf", "")})
    assert token.status_code == 201, token.text
    code = token.json()["code"]

    assert not agent_settings.state_file.exists()
    # Prompts du wizard : nom du player (vide → hostname), code d'enrôlement.
    inputs = iter(["", code])
    output: list[str] = []

    state = enroll_once(agent, agent_settings, input_fn=lambda p: next(inputs),
                        print_fn=output.append)

    assert state.device_id
    assert DeviceState.load(agent_settings.state_file) is not None
    assert any("enrôlement OK" in line for line in output)
