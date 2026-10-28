import { useState } from "react";

import { useGSAP } from "../useGsap";

/** The short cinematic intro: hairline mark, wordmark reveal, then fade into the app. */
export function Intro() {
  const [done, setDone] = useState(false);
  const scope = useGSAP<HTMLDivElement>(
    (gsap, root) => {
      gsap
        .timeline({ defaults: { ease: "expo.out" }, onComplete: () => setDone(true) })
        .from(".intro-mark", { scale: 0.6, opacity: 0, rotate: -8, duration: 0.9 })
        .fromTo(
          ".intro-word",
          { clipPath: "inset(0 100% 0 0)", letterSpacing: "0.12em" },
          { clipPath: "inset(0 0% 0 0)", letterSpacing: "-0.04em", duration: 1.1, ease: "expo.inOut" },
          "<0.1",
        )
        .from(".intro-cap", { opacity: 0, y: 6, duration: 0.6 }, "-=0.4")
        .to(".intro-stage", { opacity: 0, scale: 0.98, duration: 0.4, ease: "power2.in" }, "+=0.5")
        .to(root, { opacity: 0, duration: 0.5 });
    },
    [],
  );

  if (done || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return null;
  return (
    <div className="intro" aria-hidden="true" ref={scope} onClick={() => setDone(true)}>
      <div className="intro-stage">
        <div className="intro-mark">
          <span>3</span>
        </div>
        <h1 className="intro-word">
          M<em>3</em>allema
        </h1>
        <p className="intro-cap">Back-office intelligence · المعلّمة</p>
      </div>
    </div>
  );
}
