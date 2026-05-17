import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MockEmbeddingWarning } from "@/features/search/components/MockEmbeddingWarning";

describe("MockEmbeddingWarning", () => {
  it("renders warning text about mock embeddings", () => {
    render(<MockEmbeddingWarning />);
    expect(screen.getByText(/Semantic Search Disabled/i)).toBeInTheDocument();
    expect(screen.getByText(/EMBEDDING_USE_MOCK=true/i)).toBeInTheDocument();
  });
});
