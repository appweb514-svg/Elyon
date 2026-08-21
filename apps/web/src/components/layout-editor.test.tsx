import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

import { LayoutEditor } from "@/components/layout-editor";

function renderEditor() {
  const onChange = vi.fn();
  render(
    <LayoutEditor value={null} onChange={onChange} mediaOptions={[{ id: "m1", name: "Vidéo A" }]} playlistOptions={[{ id: "p1", name: "Playlist 1" }]} />
  );
  return { onChange };
}

describe("LayoutEditor", () => {
  it("affiche le mode plein écran par défaut avec une seule zone", () => {
    renderEditor();
    expect((screen.getByTestId("mode-select") as HTMLSelectElement).value).toBe("fullscreen");
    expect(screen.getByTestId("zone-0-x")).toBeDefined();
    expect(screen.getByTestId("zone-0-y")).toBeDefined();
    expect(screen.getByTestId("zone-0-w")).toBeDefined();
    expect(screen.getByTestId("zone-0-h")).toBeDefined();
    expect(screen.queryByTestId("zone-1-x")).toBeNull();
  });

  it("change de mode et notifie onChange avec les zones du nouveau mode", () => {
    const { onChange } = renderEditor();
    fireEvent.change(screen.getByTestId("mode-select"), { target: { value: "split_h" } });

    expect(onChange).toHaveBeenCalledTimes(1);
    const [value] = onChange.mock.calls[0];
    expect(value).toEqual({
      mode: "split_h",
      zones: [
        { x: 0, y: 0, w: 100, h: 50 },
        { x: 0, y: 50, w: 100, h: 50 },
      ],
    });
  });

  it("ajoute une zone via le bouton Ajouter et passe en mode custom", () => {
    const { onChange } = renderEditor();
    fireEvent.click(screen.getByTestId("add-zone"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const [value] = onChange.mock.calls[0];
    expect(value.mode).toBe("custom");
    expect(value.zones).toHaveLength(2);
    expect(value.zones[1]).toEqual({ x: 0, y: 0, w: 50, h: 50 });
  });

  it("met à jour les coordonnées d'une zone et notifie onChange", () => {
    const { onChange } = renderEditor();
    fireEvent.change(screen.getByTestId("zone-0-x"), { target: { value: "20" } });

    expect(onChange).toHaveBeenCalledTimes(1);
    const [value] = onChange.mock.calls[0];
    expect(value.mode).toBe("fullscreen");
    expect(value.zones[0].x).toBe(20);
    expect(value.zones[0]).toEqual({ x: 20, y: 0, w: 100, h: 100 });
  });
});
