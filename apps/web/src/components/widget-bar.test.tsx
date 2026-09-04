import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WidgetBar, type Widget } from "@/components/widget-bar";

function baseWidget(overrides: Partial<Widget> = {}): Widget {
  return {
    type: "text",
    position: "bottom-left",
    visible: true,
    params: { text: "Bonjour" },
    ...overrides,
  };
}

function mockPreviewRect(width = 300, height = 169) {
  return vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockReturnValue({
      left: 0,
      top: 0,
      right: width,
      bottom: height,
      width,
      height,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
}

const dataTransfer = {
  effectAllowed: "",
  dropEffect: "",
  data: {} as Record<string, string>,
  setData(type: string, value: string) {
    this.data[type] = value;
  },
  getData(type: string) {
    return this.data[type] ?? "";
  },
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("WidgetBar", () => {
  it("ouvre la configuration au clic (sans déplacement)", () => {
    const onOpenChange = vi.fn();
    render(
      <WidgetBar
        widgets={[baseWidget()]}
        onChange={() => undefined}
        openId={null}
        onOpenChange={onOpenChange}
      />
    );
    const pill = screen.getByLabelText(/cliquez pour configurer/i);
    fireEvent.click(pill);
    expect(onOpenChange).toHaveBeenCalledWith("0");
  });

  it("déplace le widget vers l'emplacement le plus proche au glisser", () => {
    const onChange = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <WidgetBar
        widgets={[baseWidget()]}
        onChange={onChange}
        openId={null}
        onOpenChange={onOpenChange}
      />
    );
    const pill = screen.getByLabelText(/cliquez pour configurer/i);
    const preview = screen.getByTestId("widget-preview");
    mockPreviewRect(300, 169);
    fireEvent.dragStart(pill, { dataTransfer });
    fireEvent.dragOver(preview, { dataTransfer, clientX: 260 });
    fireEvent.drop(preview, { dataTransfer, clientX: 260 });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next[0].position).toBe("bottom-right");
    expect(onOpenChange).toHaveBeenCalledWith(null);
  });

  it("n'ouvre pas la configuration via un drop sans glisser préalable", () => {
    const onChange = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <WidgetBar
        widgets={[baseWidget()]}
        onChange={onChange}
        openId={null}
        onOpenChange={onOpenChange}
      />
    );
    const preview = screen.getByTestId("widget-preview");
    mockPreviewRect(300, 169);
    fireEvent.dragOver(preview, { dataTransfer, clientX: 260 });
    fireEvent.drop(preview, { dataTransfer, clientX: 260 });
    expect(onChange).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("active la barre du haut : météo à gauche + horloge à droite verrouillées", () => {
    const onChange = vi.fn();
    render(
      <WidgetBar widgets={[]} onChange={onChange} openId={null} onOpenChange={() => undefined} />
    );
    fireEvent.click(screen.getByTestId("top-bar-toggle"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(2);
    const [weather, clock] = next;
    expect(weather).toMatchObject({ type: "weather", position: "top-left", locked: true });
    expect(clock).toMatchObject({ type: "clock", position: "top-right", locked: true });
  });

  it("désactive la barre du haut : retire météo et horloge", () => {
    const onChange = vi.fn();
    render(
      <WidgetBar
        widgets={[
          baseWidget(),
          { type: "weather", position: "top-left", visible: true, locked: true, params: { city: "Paris" } },
          { type: "clock", position: "top-right", visible: true, locked: true, params: { format: "HH:MM" } },
        ]}
        onChange={onChange}
        openId={null}
        onOpenChange={() => undefined}
      />
    );
    expect(screen.getByTestId("top-bar-toggle").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByTestId("top-bar-toggle"));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(1);
    expect(next[0].type).toBe("text");
  });

  it("active la barre du bas : ticker RSS pleine largeur verrouillé", () => {
    const onChange = vi.fn();
    render(
      <WidgetBar widgets={[]} onChange={onChange} openId={null} onOpenChange={() => undefined} />
    );
    fireEvent.click(screen.getByTestId("bottom-bar-toggle"));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({ type: "rss", position: "bottom-ticker", locked: true });
  });

  it("affiche la prévision des jours à venir avec icônes dans l'aperçu météo", () => {
    render(
      <WidgetBar
        widgets={[
          { type: "weather", position: "top-left", visible: true, locked: true, params: { city: "Paris" } },
        ]}
        onChange={() => undefined}
        openId={null}
        onOpenChange={() => undefined}
      />
    );
    expect(screen.getByText(/Paris · 12°C/)).toBeTruthy();
    // Jours à venir : libellé + max/min + icône (soleil, pluie, nuage…).
    expect(screen.getByText(/dim 24°\/15°/)).toBeTruthy();
    expect(screen.getByText(/lun 22°\/14°/)).toBeTruthy();
    expect(screen.getByText(/mar 19°\/13°/)).toBeTruthy();
    expect(screen.getByText(/mer 21°\/12°/)).toBeTruthy();
  });
});