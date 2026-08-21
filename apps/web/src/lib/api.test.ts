import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";

describe("ApiError", () => {
  it("porte le statut et le détail", () => {
    const error = new ApiError(403, "Accès refusé");
    expect(error.status).toBe(403);
    expect(error.detail).toBe("Accès refusé");
    expect(error.message).toBe("Accès refusé");
  });
});
