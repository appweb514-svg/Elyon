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

afterEach(() => {
  cleanup();
});

describe("WidgetBar", () => {
  it("ajoute un widget avec son emplacement fixe", () => {
    const onChange = vi.fn();
    render(<WidgetBar widgets={[]} onChange={onChange} openId={null} onOpenChange={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /Météo/ }));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({ type: "weather", position: "top-band", locked: true });
    expect(next[0].params.size).toBe("medium");
  });

  it("ne propose pas le widget HTML (retiré)", () => {
    render(<WidgetBar widgets={[]} onChange={() => undefined} openId={null} onOpenChange={() => undefined} />);
    expect(screen.queryByRole("button", { name: /HTML/ })).toBeNull();
  });

  it("texte libre : position fixe au centre", () => {
    const onChange = vi.fn();
    render(<WidgetBar widgets={[]} onChange={onChange} openId={null} onOpenChange={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /Texte libre/ }));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next[0]).toMatchObject({ type: "text", position: "center", locked: true });
  });

  it("déploie la configuration sous la ligne du widget (sans aperçu)", () => {
    render(
      <WidgetBar
        widgets={[baseWidget()]}
        onChange={() => undefined}
        openId="0"
        onOpenChange={() => undefined}
      />
    );
    expect(screen.getByText("Configuration")).toBeTruthy();
    expect(screen.queryByTestId("widget-preview")).toBeNull();
  });

  it("permet de changer la taille du widget (petit/moyen/grand)", () => {
    const onChange = vi.fn();
    render(
      <WidgetBar
        widgets={[baseWidget()]}
        onChange={onChange}
        openId="0"
        onOpenChange={() => undefined}
      />
    );
    fireEvent.change(screen.getByDisplayValue("Moyen"), { target: { value: "large" } });
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next[0].params.size).toBe("large");
  });

  it("active la barre du haut : météo en bandeau + horloge à droite, verrouillées", () => {
    const onChange = vi.fn();
    render(<WidgetBar widgets={[]} onChange={onChange} openId={null} onOpenChange={() => undefined} />);
    fireEvent.click(screen.getByTestId("top-bar-toggle"));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(2);
    const [weather, clock] = next;
    expect(weather).toMatchObject({ type: "weather", position: "top-band", locked: true });
    expect(clock).toMatchObject({ type: "clock", position: "top-right", locked: true });
  });

  it("désactive la barre du haut : masque météo et horloge sans perdre la config", () => {
    const onChange = vi.fn();
    render(
      <WidgetBar
        widgets={[
          baseWidget(),
          { type: "weather", position: "top-band", visible: true, locked: true, params: { city: "Paris", size: "medium" } },
          { type: "clock", position: "top-right", visible: true, locked: true, params: { format: "HH:MM", size: "medium" } },
        ]}
        onChange={onChange}
        openId={null}
        onOpenChange={() => undefined}
      />
    );
    expect(screen.getByTestId("top-bar-toggle").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByTestId("top-bar-toggle"));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(3);
    const weather = next.find((w) => w.type === "weather");
    const clock = next.find((w) => w.type === "clock");
    expect(weather).toMatchObject({ visible: false, params: { city: "Paris" } });
    expect(clock).toMatchObject({ visible: false, params: { format: "HH:MM" } });
  });

  it("réactive la barre du haut : restaure les paramètres existants", () => {
    const onChange = vi.fn();
    render(
      <WidgetBar
        widgets={[
          { type: "weather", position: "top-band", visible: false, locked: true, params: { city: "Lyon", size: "large" } },
          { type: "clock", position: "top-right", visible: false, locked: true, params: { format: "HH:MM:SS", size: "medium" } },
        ]}
        onChange={onChange}
        openId={null}
        onOpenChange={() => undefined}
      />
    );
    expect(screen.getByTestId("top-bar-toggle").getAttribute("aria-checked")).toBe("false");
    fireEvent.click(screen.getByTestId("top-bar-toggle"));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(2);
    expect(next[0]).toMatchObject({ visible: true, params: { city: "Lyon", size: "large" } });
    expect(next[1]).toMatchObject({ visible: true, params: { format: "HH:MM:SS" } });
  });

  it("désactive les boutons d'ajout quand 3 widgets sont présents", () => {
    render(
      <WidgetBar
        widgets={[baseWidget(), baseWidget({ type: "clock" }), baseWidget({ type: "rss" })]}
        onChange={() => undefined}
        openId={null}
        onOpenChange={() => undefined}
      />
    );
    expect(screen.getByRole("button", { name: /Météo/ }).hasAttribute("disabled")).toBe(true);
  });

  it("active la barre du bas : ticker RSS pleine largeur verrouillé", () => {
    const onChange = vi.fn();
    render(<WidgetBar widgets={[]} onChange={onChange} openId={null} onOpenChange={() => undefined} />);
    fireEvent.click(screen.getByTestId("bottom-bar-toggle"));
    const next = onChange.mock.calls[0][0] as Widget[];
    expect(next).toHaveLength(1);
    expect(next[0]).toMatchObject({ type: "rss", position: "bottom-ticker", locked: true });
  });
});
