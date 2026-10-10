const PASSWORD_MIN_LENGTH = 10;

const COMMON_PASSWORDS = new Set([
  "1234567890",
  "abcdefghij",
  "administrator",
  "letmein123",
  "password",
  "password123",
  "qwerty12345",
  "qwertyuiop",
  "welcome123",
]);

function isCommonPassword(password: string): boolean {
  const normalized = Array.from(password.toLowerCase())
    .filter((char) => /[\p{L}\p{N}]/u.test(char))
    .join("");
  return COMMON_PASSWORDS.has(normalized) || (normalized.length > 0 && new Set(normalized).size <= 1);
}

export function PasswordRules({ email, password }: { email: string; password: string }) {
  const localPart = email.split("@", 1)[0].toLowerCase();
  const rules = [
    {
      text: `至少 ${PASSWORD_MIN_LENGTH} 位`,
      ok: password.length >= PASSWORD_MIN_LENGTH,
    },
    {
      text: "不能包含邮箱 @ 前的名字",
      ok: localPart.length < 3 || !password.toLowerCase().includes(localPart),
    },
    {
      text: "不能使用常见密码或单一重复字符",
      ok: !isCommonPassword(password),
    },
  ];
  return (
    <ul className="flex flex-col gap-0.5 font-mono text-[11px]">
      {rules.map((rule) => (
        <li
          key={rule.text}
          className={
            !password ? "text-muted-foreground" : rule.ok ? "text-muted-foreground" : "text-destructive"
          }
        >
          {password && rule.ok ? "✓" : "·"} {rule.text}
        </li>
      ))}
    </ul>
  );
}
