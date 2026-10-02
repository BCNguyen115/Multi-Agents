import React from 'react';
import Image from 'next/image';

export function FptLogo({ className = "h-8" }: { className?: string }) {
  return (
    <div className="flex items-center shrink-0">
      <Image
        src="/FPT.VN-df6a5b44.png"
        alt="FPT Logo"
        width={100}
        height={32}
        priority
        unoptimized
        className={`${className} w-auto object-contain select-none`}
      />
    </div>
  );
}
