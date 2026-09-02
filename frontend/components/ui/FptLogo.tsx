import React from 'react';

export function FptLogo({ className = "h-8" }: { className?: string }) {
  return (
    <div className="flex items-center shrink-0">
      <img
        src="/FPT.VN-df6a5b44.png"
        alt="FPT Logo"
        className={`${className} w-auto object-contain select-none`}
      />
    </div>
  );
}
