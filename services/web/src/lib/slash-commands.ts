export type SlashScope = "reference";

export interface SlashCommandResult {
  scope: SlashScope;
  query: string;
  displayLabel: string;
}

interface SlashCommandDef {
  scope: SlashScope;
  displayLabel: string;
}

const SLASH_COMMANDS: Record<string, SlashCommandDef> = {
  "/레퍼런스": { scope: "reference", displayLabel: "레퍼런스" },
};

export function parseSlashCommand(input: string): SlashCommandResult | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/")) return null;

  for (const [prefix, meta] of Object.entries(SLASH_COMMANDS)) {
    if (trimmed === prefix || trimmed.startsWith(prefix + " ")) {
      const query = trimmed.slice(prefix.length).trim();
      return { scope: meta.scope, query, displayLabel: meta.displayLabel };
    }
  }
  return null;
}

export interface SlashCommandSuggestion {
  command: string;
  description: string;
}

export function getSlashCommandSuggestions(): SlashCommandSuggestion[] {
  return [
    { command: "/레퍼런스", description: "유튜브 레퍼런스 영상에서 검색" },
  ];
}
