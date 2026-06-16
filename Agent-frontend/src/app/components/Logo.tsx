import { LOGO_DATA_URI } from "./logo-data";

// The RSAgent mark from the project repo (docs/assets/logo-rsagent.png),
// inlined as a data URI so it always renders in the Make preview.
const logoUrl = LOGO_DATA_URI;

/**
 * RSAgent brand mark (from the project repo). The source PNG sits on a white
 * field, so we present it inside a light rounded chip to read cleanly on the
 * dark UI. `object-contain` keeps the full lockup intact.
 */
export function Logo({
  size = 36,
  rounded = "rounded-xl",
  className = "",
}: {
  size?: number;
  rounded?: string;
  className?: string;
}) {
  return (
    <div
      className={`grid shrink-0 place-items-center overflow-hidden bg-white ${rounded} ${className}`}
      style={{ width: size, height: size }}
    >
      <img
        src={logoUrl}
        alt="RSAgent"
        className="size-full object-contain"
        style={{ padding: Math.round(size * 0.08) }}
        draggable={false}
      />
    </div>
  );
}
