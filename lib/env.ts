/** Read a required server-side env var; throws a clear error when missing. */
export function env(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing environment variable ${name}. See .env.example.`);
  return v;
}
export const optionalEnv = (name: string): string | undefined => process.env[name] || undefined;
