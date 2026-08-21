import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Page from "./page";

describe("Page", () => {
  it("rend le composant Page avec le texte Elyon", () => {
    render(<Page />);
    expect(screen.getByText("Elyon")).toBeTruthy();
  });
});