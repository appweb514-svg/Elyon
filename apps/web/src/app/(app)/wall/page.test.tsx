import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue([
      {
        device_id: "prev",
        name: "Aperçu administrateur",
        serial: "emu-rpi-preview",
        is_preview: true,
        status: "approved",
        computed_status: "online",
        player_state: "playing",
        current_media_id: "m1",
        current_media_name: "Spot",
        current_media_kind: "image",
        last_seen_at: null,
        screen_id: "s1",
      },
      {
        device_id: "p1",
        name: "Raspberry émulé 1",
        serial: "emu-rpi-1",
        is_preview: false,
        status: "approved",
        computed_status: "online",
        player_state: "playing",
        current_media_id: "m1",
        current_media_name: "Spot",
        current_media_kind: "image",
        last_seen_at: null,
        screen_id: "s2",
      },
    ]),
  },
}));

import Page from "./page";

describe("Mur d'écrans", () => {
  it("affiche l'aperçu admin et les players", async () => {
    render(<Page />);
    expect(await screen.findByText("Mur d'écrans")).toBeDefined();
    expect(await screen.findByText("Aperçu avant publication")).toBeDefined();
    expect(await screen.findByText("Aperçu administrateur")).toBeDefined();
    expect(await screen.findByText("BROUILLON")).toBeDefined();
    expect(await screen.findByText("Raspberry émulé 1")).toBeDefined();
  });
});
