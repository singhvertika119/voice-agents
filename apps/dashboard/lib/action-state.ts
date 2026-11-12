// What a form's server action returns, shown under the form by <FormResult>. null before the first submit.
export type ActionState = { ok: boolean; message: string } | null;

export const fail = (message: string): ActionState => ({ ok: false, message });
export const done = (message: string): ActionState => ({ ok: true, message });

type DbError = { code?: string; message: string } | null | undefined;

// Plain words for a database error. The raw message (table names, constraint names) goes to the server log only.
export function dbMessage(error: DbError, fallback = "Something went wrong. Please try again."): string {
  if (!error) return fallback;
  console.error("database error:", error.code, error.message);
  if (error.code === "23505") return "That already exists.";
  if (error.code === "23503") return "Something else still uses this, so it cannot be changed.";
  if (error.code === "42501" || /row-level security|permission denied/i.test(error.message)) return "You do not have permission to do that.";
  if (error.code === "PGRST116") return "That could not be found. Refresh the page and try again.";
  return fallback;
}
