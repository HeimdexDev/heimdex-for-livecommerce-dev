import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { TagFilterInput } from "@/features/search/components/TagFilterInput";
import { TagFilters } from "@/features/search/components/TagFilters";
import type { SearchFilters } from "@/lib/types/search";

describe("TagFilterInput", () => {
  it("renders empty input with placeholder", () => {
    render(<TagFilterInput tags={[]} onChange={() => {}} placeholder="Add tags" />);
    expect(screen.getByPlaceholderText("Add tags")).toBeInTheDocument();
  });

  it("renders existing tags as chips", () => {
    render(<TagFilterInput tags={["할인", "프로모션"]} onChange={() => {}} />);
    expect(screen.getByText("할인")).toBeInTheDocument();
    expect(screen.getByText("프로모션")).toBeInTheDocument();
  });

  it("adds a tag on Enter", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<TagFilterInput tags={[]} onChange={onChange} />);
    const input = screen.getByTestId("tag-filter-input");

    await user.type(input, "new-tag{Enter}");

    expect(onChange).toHaveBeenCalledWith(["new-tag"]);
  });

  it("trims whitespace before adding", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<TagFilterInput tags={[]} onChange={onChange} />);
    const input = screen.getByTestId("tag-filter-input");

    await user.type(input, "  spaced  {Enter}");

    expect(onChange).toHaveBeenCalledWith(["spaced"]);
  });

  it("ignores empty input on Enter", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<TagFilterInput tags={[]} onChange={onChange} />);
    const input = screen.getByTestId("tag-filter-input");

    await user.type(input, "   {Enter}");

    expect(onChange).not.toHaveBeenCalled();
  });

  it("prevents duplicate tags", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<TagFilterInput tags={["existing"]} onChange={onChange} />);
    const input = screen.getByTestId("tag-filter-input");

    await user.type(input, "existing{Enter}");

    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes a tag when X button is clicked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<TagFilterInput tags={["tag-a", "tag-b"]} onChange={onChange} />);
    const removeBtn = screen.getByRole("button", { name: "Remove tag-a" });

    await user.click(removeBtn);

    expect(onChange).toHaveBeenCalledWith(["tag-b"]);
  });

  it("removes last tag on Backspace when input is empty", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<TagFilterInput tags={["first", "second"]} onChange={onChange} />);
    const input = screen.getByTestId("tag-filter-input");

    await user.click(input);
    await user.keyboard("{Backspace}");

    expect(onChange).toHaveBeenCalledWith(["first"]);
  });

  it("shows limit warning when maxItems reached", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const tags = Array.from({ length: 50 }, (_, i) => `tag-${i}`);

    render(<TagFilterInput tags={tags} onChange={onChange} maxItems={50} />);
    const input = screen.getByTestId("tag-filter-input");

    await user.type(input, "overflow{Enter}");

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("Maximum 50 tags allowed")).toBeInTheDocument();
  });

  it("hides placeholder when tags exist", () => {
    render(<TagFilterInput tags={["tag"]} onChange={() => {}} placeholder="Add tags" />);
    expect(screen.queryByPlaceholderText("Add tags")).not.toBeInTheDocument();
  });
});

describe("TagFilters", () => {
  const emptyFilters: SearchFilters = {};

  it("renders all 6 tag input areas", () => {
    render(<TagFilters filters={emptyFilters} onFiltersChange={() => {}} />);

    expect(screen.getByText("Keyword tags")).toBeInTheDocument();
    expect(screen.getByText("Product tags")).toBeInTheDocument();
    expect(screen.getByText("Product entities")).toBeInTheDocument();

    const includeLabels = screen.getAllByText("Include");
    const excludeLabels = screen.getAllByText("Exclude");
    expect(includeLabels).toHaveLength(3);
    expect(excludeLabels).toHaveLength(3);
  });

  it("renders helper text for product entities", () => {
    render(<TagFilters filters={emptyFilters} onFiltersChange={() => {}} />);
    expect(screen.getByText(/모이스처라이저/)).toBeInTheDocument();
  });

  it("shows 'Clear tags' button only when tags are present", () => {
    const { rerender } = render(
      <TagFilters filters={emptyFilters} onFiltersChange={() => {}} />
    );
    expect(screen.queryByText("Clear tags")).not.toBeInTheDocument();

    rerender(
      <TagFilters
        filters={{ keyword_tags_in: ["할인"] }}
        onFiltersChange={() => {}}
      />
    );
    expect(screen.getByText("Clear tags")).toBeInTheDocument();
  });

  it("clears all tag filters when 'Clear tags' is clicked", async () => {
    const onFiltersChange = vi.fn();
    const user = userEvent.setup();

    const filters: SearchFilters = {
      source_types: ["gdrive"],
      keyword_tags_in: ["할인"],
      product_tags_not_in: ["alcohol"],
    };

    render(<TagFilters filters={filters} onFiltersChange={onFiltersChange} />);

    await user.click(screen.getByText("Clear tags"));

    const result = onFiltersChange.mock.calls[0][0] as SearchFilters;
    expect(result.source_types).toEqual(["gdrive"]);
    expect(result.keyword_tags_in).toBeUndefined();
    expect(result.product_tags_not_in).toBeUndefined();
  });

  it("renders existing tag chips in correct inputs", () => {
    const filters: SearchFilters = {
      keyword_tags_in: ["할인", "프로모션"],
      product_entities_not_in: ["BadBrand"],
    };

    render(<TagFilters filters={filters} onFiltersChange={() => {}} />);

    expect(screen.getByText("할인")).toBeInTheDocument();
    expect(screen.getByText("프로모션")).toBeInTheDocument();
    expect(screen.getByText("BadBrand")).toBeInTheDocument();
  });

  it("calls onFiltersChange with updated include field", async () => {
    const onFiltersChange = vi.fn();
    const user = userEvent.setup();

    render(<TagFilters filters={emptyFilters} onFiltersChange={onFiltersChange} />);

    const inputs = screen.getAllByTestId("tag-filter-input");
    await user.type(inputs[0], "새태그{Enter}");

    expect(onFiltersChange).toHaveBeenCalledWith(
      expect.objectContaining({ keyword_tags_in: ["새태그"] })
    );
  });

  it("calls onFiltersChange with updated exclude field", async () => {
    const onFiltersChange = vi.fn();
    const user = userEvent.setup();

    render(<TagFilters filters={emptyFilters} onFiltersChange={onFiltersChange} />);

    const inputs = screen.getAllByTestId("tag-filter-input");
    await user.type(inputs[1], "제외태그{Enter}");

    expect(onFiltersChange).toHaveBeenCalledWith(
      expect.objectContaining({ keyword_tags_not_in: ["제외태그"] })
    );
  });

  it("sets field to undefined when last tag removed", async () => {
    const onFiltersChange = vi.fn();
    const user = userEvent.setup();

    const filters: SearchFilters = { keyword_tags_in: ["only-tag"] };
    render(<TagFilters filters={filters} onFiltersChange={onFiltersChange} />);

    const removeBtn = screen.getByRole("button", { name: "Remove only-tag" });
    await user.click(removeBtn);

    const result = onFiltersChange.mock.calls[0][0] as SearchFilters;
    expect(result.keyword_tags_in).toBeUndefined();
  });
});
