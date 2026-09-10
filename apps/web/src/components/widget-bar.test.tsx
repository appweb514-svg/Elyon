import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WidgetBar, type Widget } from "@/components/widget-bar";

function baseWidget(overrides: Partial<Widget> = {}): Widget {
  return {
    type: "text",
    position: "center",
    visible: true,
    params: { text: "Bonjour", size: "medium" },
    ...overrides,
  };
}

afterEach(() => cleanup());

describe("WidgetBar", () => {
  it("ajoute un widget avec son emplacement fixe", () => {
    const onChange = vi.fn();
    render(<WidgetBar widgets={[]} onChange={onChange} openId={null} onOpenChange={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /Météo/ }));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({ type: "weather", position: "top-band", locked: true });
  });

  it("ne propose pas le widget HTML retiré", () => {
    render(<WidgetBar widgets={[]} onChange={() => undefined} openId={null} onOpenChange={() => undefined} />);
    expect(screen.queryByRole("button", { name: /HTML/ })).toBeNull();
  });

  it("texte libre : position fixe au centre", () => {
    const onChange = vi.fn();
    render(<WidgetBar widgets={[]} onChange={onChange} openId={null} onOpenChange={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /Texte libre/ }));
    expect((onChange.mock.calls[0][0] as Widget[])[0]).toMatchObject({ type: "text", position: "center" });
  });

  it("déploie la configuration sous la ligne du widget", () => {
    render(<WidgetBar widgets={[baseWidget()]} onChange={() => undefined} openId="0" onOpenChange={() => undefined} />);
    expect(screen.getByText("Configuration")).toBeTruthy();
  });

  it("permet de changer la taille du widget", () => {
    const onChange = vi.fn();
    render(<WidgetBar widgets={[baseWidget()]} onChange={onChange} openId="0" onOpenChange={() => undefined} />);
    fireEvent.change(screen.getByDisplayValue("Moyen"), { target: { value: "large" } });
    expect((onChange.mock.calls[0][0] as Widget[])[0].params.size).toBe("large");
  });

  it("refuse d'ajouter un quatrième widget", () => {
    const onChange = vi.fn();
    render(
      <WidgetBar
        widgets={[baseWidget(), baseWidget({ type: "clock" }), baseWidget({ type: "rss" })]}
        onChange={onChange}
        openId={null}
        onOpenChange={() => undefined}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Météo/ }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
