import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

describe("composants UI", () => {
  it("Badge rend son contenu avec variante success", () => {
    render(<Badge variant="success">approved</Badge>);
    const badge = screen.getByText("approved");
    expect(badge.className).toContain("bg-emerald-600");
  });

  it("Button rend un bouton désactivable", () => {
    render(
      <Button variant="destructive" disabled>
        Supprimer
      </Button>
    );
    const button = screen.getByRole("button", { name: "Supprimer" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(button.className).toContain("bg-destructive");
  });
});
