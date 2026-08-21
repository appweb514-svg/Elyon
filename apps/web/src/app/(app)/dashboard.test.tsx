import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({
      devices_total: 3,
      devices_online: 2,
      devices_pending: 1,
      media_count: 5,
      recent_events: [],
    }),
  },
  formatDate: (v: string | null) => v ?? "—",
}));

import Page from "@/app/(app)/page";

describe("Tableau de bord", () => {
  it("affiche les compteurs", async () => {
    render(<Page />);
    expect(await screen.findByText("Tableau de bord")).toBeDefined();
    expect(await screen.findByText("Médias")).toBeDefined();
    expect(await screen.findByText("5")).toBeDefined();
  });
});
