interface BlueboltLogoProps {
  className?: string;
  /** "full" = icon + text, "icon" = icon only, "text" = text only */
  variant?: "full" | "icon" | "text";
  size?: "sm" | "md" | "lg";
}

const sizes = {
  sm: { icon: 28, fontSize: 13, subFontSize: 8 },
  md: { icon: 38, fontSize: 18, subFontSize: 10 },
  lg: { icon: 52, fontSize: 24, subFontSize: 13 },
};

export function BlueboltLogo({
  className = "",
  variant = "full",
  size = "md",
}: BlueboltLogoProps) {
  const s = sizes[size];

  const Icon = (
    <svg
      width={s.icon}
      height={s.icon}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Top stripe — dark blue, rotated ~-40deg */}
      <rect
        x="18" y="6"
        width="64" height="22"
        rx="11"
        fill="#1e40af"
        transform="rotate(-40 50 50)"
      />
      {/* Bottom stripe — orange, rotated ~-40deg, offset down-right */}
      <rect
        x="18" y="30"
        width="64" height="22"
        rx="11"
        fill="#f97316"
        transform="rotate(-40 50 50)"
      />
    </svg>
  );

  if (variant === "icon") return <span className={className}>{Icon}</span>;

  const Text = (
    <span className="flex flex-col leading-none">
      <span style={{ fontSize: s.fontSize }} className="font-extrabold tracking-tight">
        <span style={{ color: "#1e40af" }}>BLUE</span>
        <span style={{ color: "#f97316" }}>BOLT</span>
      </span>
      {variant === "full" && (
        <span
          style={{ fontSize: s.subFontSize, color: "#94a3b8", letterSpacing: "0.18em" }}
          className="font-semibold uppercase"
        >
          SOFTWARE
        </span>
      )}
    </span>
  );

  if (variant === "text") return <span className={className}>{Text}</span>;

  return (
    <span className={`flex items-center gap-2 ${className}`}>
      {Icon}
      {Text}
    </span>
  );
}
