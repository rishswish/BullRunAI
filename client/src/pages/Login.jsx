import React from "react";
import { GoogleLogin } from "@react-oauth/google";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  ChevronDown,
  Clock3,
  LineChart,
  Mail,
  Play,
  Sparkles,
} from "lucide-react";
import brLogo from "../assets/br.png";
import recording from "../assets/Recording 2025-10-28 104816.mp4";
import "./Login.css";

const EMAIL_PATTERN = /^[^@]+@[^@]+\.[^@]+$/;

const PLATFORM_ITEMS = [
  {
    title: "Briefings",
    body: "Daily market reads built around your watchlist and holdings.",
  },
  {
    title: "Watchlists",
    body: "Track tickers, catalysts, and the moves that deserve attention.",
  },
  {
    title: "Portfolio context",
    body: "Connect market news to the names and sectors you already own.",
  },
  {
    title: "Research assistant",
    body: "Ask follow-up questions without losing the source context.",
  },
  {
    title: "Market data",
    body: "Live prices, sector moves, and news signals in one workspace.",
  },
];

const PRODUCT_CARDS = [
  {
    title: "Daily brief",
    body: "One clean read on what moved, why it matters, and what to watch next.",
    tone: "dark",
  },
  {
    title: "Watchlist monitor",
    body: "See which companies, sectors, and themes are leading the tape.",
    tone: "blue",
  },
  {
    title: "Portfolio impact",
    body: "Understand exposure before market noise turns into a decision.",
    tone: "sand",
  },
  {
    title: "Research chat",
    body: "Ask BullRun to explain filings, news, and price moves in context.",
    tone: "teal",
  },
];

const decodeJwtPayload = (token) => {
  const payload = token?.split(".")[1];
  if (!payload) return {};
  const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  return JSON.parse(window.atob(padded));
};

const openProductTourFullscreen = () => {
  if (typeof document === "undefined") return;

  document
    .querySelectorAll(".br-fullscreen-tour-video")
    .forEach((existingVideo) => existingVideo.remove());

  const video = document.createElement("video");
  video.src = recording;
  video.controls = true;
  video.autoplay = true;
  video.playsInline = true;
  video.preload = "auto";
  video.className = "br-fullscreen-tour-video";
  video.setAttribute("aria-label", "BullRun product tour");

  let cleaned = false;

  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    document.removeEventListener("fullscreenchange", handleFullscreenChange);
    document.removeEventListener(
      "webkitfullscreenchange",
      handleFullscreenChange,
    );
    window.removeEventListener("keydown", handleKeydown);
    video.pause();
    video.remove();
  };

  const handleFullscreenChange = () => {
    const fullscreenElement =
      document.fullscreenElement || document.webkitFullscreenElement;
    if (!fullscreenElement) cleanup();
  };

  const handleKeydown = (event) => {
    if (event.key !== "Escape") return;
    if (document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    } else if (
      document.webkitFullscreenElement &&
      document.webkitExitFullscreen
    ) {
      document.webkitExitFullscreen();
    } else {
      cleanup();
    }
  };

  document.addEventListener("fullscreenchange", handleFullscreenChange);
  document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
  window.addEventListener("keydown", handleKeydown);
  video.addEventListener("ended", cleanup, { once: true });
  document.body.appendChild(video);
  video.load();

  const playVideo = () => {
    video.currentTime = 0;
    const playback = video.play();
    if (playback?.catch) {
      playback.catch(() => {
        video.muted = true;
        video.play().catch(() => {});
      });
    }
  };

  playVideo();

  if (video.requestFullscreen) {
    video.requestFullscreen().catch(() => {
      playVideo();
    });
  } else if (video.webkitRequestFullscreen) {
    video.webkitRequestFullscreen();
  } else if (video.webkitEnterFullscreen) {
    video.webkitEnterFullscreen();
  }
};

function BrandMark() {
  return (
    <button type="button" className="br-brand" aria-label="BullRun home">
      <img src={brLogo} alt="" className="br-brand__logo" />
      <span>BullRun</span>
    </button>
  );
}

function PublicNav({ onOpenTour }) {
  const navigate = useNavigate();
  const [platformOpen, setPlatformOpen] = React.useState(false);

  const goHome = () => navigate("/");
  const goLogin = () => navigate("/login");
  const goSales = () => navigate("/sales");
  const goWhitepaper = () => navigate("/whitepaper");
  const openTour = () => {
    setPlatformOpen(false);
    if (onOpenTour) {
      onOpenTour();
      return;
    }
    openProductTourFullscreen();
  };

  return (
    <header
      className="br-public-nav"
      onMouseLeave={() => setPlatformOpen(false)}
    >
      <div className="br-public-nav__inner">
        <div className="br-public-nav__left">
          <div onClick={goHome}>
            <BrandMark />
          </div>

          <nav className="br-public-nav__links" aria-label="Public navigation">
            <button
              type="button"
              className={`br-nav-link ${platformOpen ? "is-active" : ""}`}
              onClick={() => setPlatformOpen((open) => !open)}
              onMouseEnter={() => setPlatformOpen(true)}
              aria-expanded={platformOpen}
            >
              Platform
              <ChevronDown size={15} />
            </button>
            <button
              type="button"
              className="br-nav-link"
              onClick={goWhitepaper}
            >
              Whitepaper
            </button>
            <button type="button" className="br-nav-link" onClick={goSales}>
              Enterprise
            </button>
          </nav>
        </div>

        <div className="br-public-nav__actions">
          <button type="button" className="br-nav-text" onClick={goLogin}>
            Sign in
          </button>
          <button type="button" className="br-nav-pill" onClick={goSales}>
            Talk to sales
          </button>
          <button
            type="button"
            className="br-nav-pill br-nav-pill--dark"
            onClick={goLogin}
          >
            Get started
          </button>
        </div>
      </div>

      {platformOpen ? <PlatformDropdown onTour={openTour} /> : null}
    </header>
  );
}

function PlatformDropdown({ onTour }) {
  return (
    <div className="br-platform-menu">
      <div className="br-platform-menu__inner">
        <div className="br-platform-menu__list">
          {PLATFORM_ITEMS.map((item) => (
            <article key={item.title} className="br-platform-menu__item">
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </article>
          ))}
        </div>

        <button
          type="button"
          className="br-platform-menu__tour"
          onClick={onTour}
        >
          <span className="br-platform-menu__media">
            <video src={recording} muted loop autoPlay playsInline />
            <span className="br-platform-menu__play">
              <Play size={20} fill="currentColor" />
            </span>
          </span>
          <strong>Watch product tour</strong>
          <small>See how BullRun turns a portfolio into a market brief.</small>
        </button>
      </div>
    </div>
  );
}

function ScrollGrowVideo({ onOpenTour }) {
  const cardRef = React.useRef(null);
  const rafRef = React.useRef(0);
  const scaleRef = React.useRef(1);
  const targetRef = React.useRef(1);

  React.useEffect(() => {
    const reduceMotion = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    )?.matches;
    if (reduceMotion) return undefined;

    const animate = () => {
      const card = cardRef.current;
      if (!card) {
        rafRef.current = 0;
        return;
      }

      scaleRef.current += (targetRef.current - scaleRef.current) * 0.085;
      card.style.transform = `scale(${scaleRef.current.toFixed(4)})`;

      if (Math.abs(targetRef.current - scaleRef.current) > 0.001) {
        rafRef.current = window.requestAnimationFrame(animate);
      } else {
        scaleRef.current = targetRef.current;
        rafRef.current = 0;
      }
    };

    const updateTarget = () => {
      const card = cardRef.current;
      if (!card) return;

      const rect = card.getBoundingClientRect();
      const viewport = window.innerHeight || 1;
      const progress = Math.min(
        1,
        Math.max(0, (viewport * 0.58 - rect.top) / (viewport * 0.62)),
      );
      targetRef.current = 1 + progress * 0.045;

      if (!rafRef.current) {
        rafRef.current = window.requestAnimationFrame(animate);
      }
    };

    const scrollTargets = [
      window,
      document,
      document.body,
      document.documentElement,
      cardRef.current?.closest(".br-public-page"),
    ].filter(Boolean);

    updateTarget();
    scrollTargets.forEach((target) =>
      target.addEventListener("scroll", updateTarget, { passive: true }),
    );
    window.addEventListener("resize", updateTarget);

    return () => {
      scrollTargets.forEach((target) =>
        target.removeEventListener("scroll", updateTarget),
      );
      window.removeEventListener("resize", updateTarget);
      if (rafRef.current) window.cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <section className="br-tour" id="demo" aria-label="BullRun product tour">
      <div className="br-tour__card" ref={cardRef}>
        <video src={recording} muted loop autoPlay playsInline />
        <div className="br-tour__shade" />
        <button type="button" className="br-tour__play" onClick={onOpenTour}>
          <span>
            <strong>Watch product tour</strong>
            <small>4 minutes</small>
          </span>
          <span className="br-tour__play-icon">
            <Play size={22} fill="currentColor" />
          </span>
        </button>
      </div>
    </section>
  );
}

function ProductCard({ item }) {
  return (
    <article className={`br-product-card br-product-card--${item.tone}`}>
      <h3>{item.title}</h3>
      <p>{item.body}</p>
      <button
        type="button"
        className="br-product-card__arrow"
        aria-label={`Open ${item.title}`}
      >
        <ArrowUpRight size={21} />
      </button>
      <div className="br-product-card__mock" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </article>
  );
}

function LandingPage() {
  const navigate = useNavigate();
  const [trialEmail, setTrialEmail] = React.useState("");

  const goLogin = () => navigate("/login");
  const goSales = () => navigate("/sales");
  const openTour = React.useCallback(() => openProductTourFullscreen(), []);
  const submitTrial = (event) => {
    event.preventDefault();
    const email = trialEmail.trim();
    navigate(email ? `/login?email=${encodeURIComponent(email)}` : "/login");
  };

  return (
    <div className="br-public-page">
      <PublicNav onOpenTour={openTour} />

      <main>
        <div className="br-announcement">
          Portfolio-aware market briefings for active investors.
          <button type="button" onClick={openTour}>
            Watch product tour
            <ArrowRight size={17} />
          </button>
        </div>

        <section className="br-hero">
          <h1>The Platform for AI Investing</h1>
          <p>
            BullRun helps investors understand the market, their portfolio, and
            the signals that matter in a clear and flexible way.
          </p>
          <div className="br-hero__actions">
            <button
              type="button"
              className="br-button br-button--dark"
              onClick={goLogin}
            >
              Start free trial
            </button>
            <button
              type="button"
              className="br-button br-button--light"
              onClick={goSales}
            >
              Talk to sales
            </button>
          </div>
        </section>

        <ScrollGrowVideo onOpenTour={openTour} />

        <section className="br-proof">
          <div>
            <h2>
              Built for investors who need market context before the open.
              <span>
                Clear enough for a morning read. Structured enough for real
                decisions.
              </span>
            </h2>
            <button type="button" onClick={goLogin}>
              <ArrowRight size={24} />
              Start free trial
            </button>
          </div>
          <blockquote>
            BullRun is designed to replace scattered tabs, noisy feeds, and
            generic AI answers with a portfolio-aware workspace for daily market
            research.
          </blockquote>
        </section>

        <section className="br-product-rail" id="platform">
          <h2>
            The essential market AI stack.
            <span>
              Simple for daily users. Ready for deeper research workflows.
            </span>
          </h2>
          <div className="br-product-rail__track">
            {PRODUCT_CARDS.map((item) => (
              <ProductCard key={item.title} item={item} />
            ))}
          </div>
        </section>

        <section className="br-final-trial" id="pricing">
          <h2>Explore BullRun with a free trial.</h2>
          <form onSubmit={submitTrial}>
            <input
              type="email"
              value={trialEmail}
              onChange={(event) => setTrialEmail(event.target.value)}
              placeholder="Enter your work email"
              aria-label="Work email"
            />
            <button type="submit">Get started</button>
          </form>
          <p>
            No credit card required. Or{" "}
            <button type="button" onClick={goSales}>
              talk to sales
            </button>
            .
          </p>
        </section>
      </main>

      <PublicFooter />
    </div>
  );
}

function PublicFooter() {
  const navigate = useNavigate();

  return (
    <footer className="br-footer">
      <div className="br-footer__brandline">
        <div className="br-brand br-brand--static">
          <img src={brLogo} alt="" className="br-brand__logo" />
          <span>BullRun</span>
        </div>
        <p>
          Portfolio-aware market intelligence for daily research and investing
          workflows.
        </p>
      </div>

      <button
        type="button"
        className="br-footer__whitepaper"
        onClick={() => navigate("/whitepaper")}
      >
        Whitepaper
        <ArrowRight size={18} />
      </button>
    </footer>
  );
}

function WhitepaperPage() {
  return (
    <div className="br-public-page br-public-page--doc">
      <PublicNav />

      <main className="br-whitepaper">
        <aside className="br-whitepaper__toc" aria-label="Whitepaper sections">
          <span>Whitepaper</span>
          <a href="#overview">Overview</a>
          <a href="#thesis">Product thesis</a>
          <a href="#workflow">User workflow</a>
          <a href="#system">System architecture</a>
          <a href="#data">Data model</a>
          <a href="#reports">AI reports</a>
          <a href="#api">API surface</a>
          <a href="#infrastructure">Infrastructure</a>
          <a href="#guardrails">Guardrails</a>
        </aside>

        <article className="br-whitepaper__article">
          <header className="br-whitepaper__hero" id="overview">
            <p>BullRunAI Whitepaper</p>
            <h1>
              AI-powered market briefings built around watchlists and
              portfolios.
            </h1>
            <div>
              BullRunAI is a personalized investing workspace that turns a
              user's watchlist, brokerage portfolio, live market data, and
              recent news into a daily market briefing. The product is built to
              answer a simple question: what changed in the market, why does it
              matter, and what should this specific investor watch next?
            </div>
            <blockquote>
              BullRunAI is for market education and research. It is not
              financial advice.
            </blockquote>
          </header>

          <section className="br-whitepaper__section" id="thesis">
            <h2>Product Thesis</h2>
            <p>
              Most consumer investing tools split the daily workflow across
              market data, brokerages, news feeds, charts, and generic AI chat.
              BullRunAI combines those surfaces into one portfolio-aware context
              layer. The application does not just show that a stock moved; it
              connects that move to the user's watchlist, holdings, benchmarks,
              recent news, and near-term catalysts.
            </p>
            <div className="br-doc-grid br-doc-grid--three">
              <article>
                <strong>Market context</strong>
                <span>
                  Polygon powers quotes, movers, news, company profiles, and
                  chart series so the workspace starts with live market data.
                </span>
              </article>
              <article>
                <strong>Portfolio context</strong>
                <span>
                  SnapTrade lets users connect brokerages and turn account
                  balances, positions, orders, and top holdings into research
                  inputs.
                </span>
              </article>
              <article>
                <strong>AI context</strong>
                <span>
                  Gemini generates global and personal reports from grounded
                  facts, user preferences, watchlists, and portfolio exposure.
                </span>
              </article>
            </div>
          </section>

          <section className="br-whitepaper__section" id="workflow">
            <h2>End-to-End User Workflow</h2>
            <p>
              The product flow is intentionally simple: collect enough context
              to understand the investor, then keep that context available
              across market summaries, ticker pages, portfolio analysis, and
              chat.
            </p>
            <div className="br-doc-flow">
              <article>
                <b>01</b>
                <strong>Authenticate</strong>
                <span>
                  Google OAuth signs users in. The client caches user and
                  profile data for one hour to avoid repeated loading states.
                </span>
              </article>
              <article>
                <b>02</b>
                <strong>Personalize</strong>
                <span>
                  Onboarding captures experience level, investing goal,
                  interests, and a minimum watchlist so the first dashboard has
                  relevant context.
                </span>
              </article>
              <article>
                <b>03</b>
                <strong>Brief</strong>
                <span>
                  The dashboard loads the latest personal report when it exists,
                  then falls back to the latest global market report.
                </span>
              </article>
              <article>
                <b>04</b>
                <strong>Connect</strong>
                <span>
                  The portfolio page can generate a SnapTrade connection portal
                  URL and aggregate linked accounts once the user completes the
                  connection.
                </span>
              </article>
              <article>
                <b>05</b>
                <strong>Research</strong>
                <span>
                  Ticker pages combine price, company profile, news, and
                  benchmark charting across multiple timeframes.
                </span>
              </article>
              <article>
                <b>06</b>
                <strong>Ask</strong>
                <span>
                  A finance-scoped Gemini chatbot gives follow-up explanations
                  without leaving the BullRun workspace.
                </span>
              </article>
            </div>
          </section>

          <section className="br-whitepaper__section" id="system">
            <h2>System Architecture</h2>
            <p>
              BullRunAI separates the real-time product surface from slower AI
              generation work. The API remains responsive for user actions while
              report agents run independently as Cloud Run Jobs.
            </p>
            <div className="br-architecture" aria-label="System architecture">
              <article>
                <strong>Client service</strong>
                <span>
                  br-client is a React + Vite app served from Cloud Run. It
                  handles unauthenticated marketing pages, Google sign-in,
                  onboarding, dashboard, ticker research, and portfolio UI.
                </span>
              </article>
              <article>
                <strong>API service</strong>
                <span>
                  br-server is a Flask + Gunicorn API on Cloud Run. It verifies
                  Google tokens, reads and writes Firestore, calls Polygon and
                  SnapTrade, and proxies Gemini chat requests.
                </span>
              </article>
              <article>
                <strong>Global report job</strong>
                <span>
                  br-global-agent creates a market-wide briefing from grounded
                  search facts and writes hourly reports to Firestore.
                </span>
              </article>
              <article>
                <strong>Personal report job</strong>
                <span>
                  br-personal-report-agent iterates onboarded users, collects
                  portfolio and watchlist context, generates one report per user
                  per day, and stores trace data with the output.
                </span>
              </article>
              <article>
                <strong>External data plane</strong>
                <span>
                  Polygon supplies snapshots, movers, news, company details, and
                  aggregate chart series. SnapTrade supplies connected account
                  data and read-only portfolio access.
                </span>
              </article>
              <article>
                <strong>Build and release plane</strong>
                <span>
                  GitHub pushes feed Cloud Build, Docker images are stored in
                  Artifact Registry, and Cloud Run deploys frontend, backend,
                  and job images independently.
                </span>
              </article>
            </div>
          </section>

          <section className="br-whitepaper__section" id="data">
            <h2>Data Model and Storage</h2>
            <p>
              Firestore is the product's operating database. The early data
              model is document-oriented because the primary objects are user
              profiles, onboarding state, watchlists, brokerage mappings, and
              generated reports.
            </p>
            <div className="br-whitepaper__table" role="table">
              <div role="row">
                <b>Collection or object</b>
                <b>Stored data</b>
                <b>Why it exists</b>
              </div>
              <div role="row">
                <span>users/{`{email}`}</span>
                <span>
                  Email, name, avatar, onboarding fields, watchlist, SnapTrade
                  credentials, timestamps.
                </span>
                <span>
                  Serves as the profile record and the root for all
                  user-specific personalization.
                </span>
              </div>
              <div role="row">
                <span>
                  users/{`{email}`}/reports/{`{date}`}
                </span>
                <span>
                  Personalized headline, summary, key movements, implications,
                  watch points, model, facts, portfolio data, watchlist data.
                </span>
                <span>
                  Stores a daily report and preserves the inputs that shaped the
                  output for traceability.
                </span>
              </div>
              <div role="row">
                <span>reports/{`{hour}`}</span>
                <span>
                  Global market report, generated timestamp, model, and grounded
                  fact pack.
                </span>
                <span>
                  Gives every user a high-quality fallback briefing even before
                  they connect a brokerage.
                </span>
              </div>
            </div>
          </section>

          <section className="br-whitepaper__section" id="reports">
            <h2>AI Report Generation</h2>
            <p>
              BullRunAI does not ask a model to invent a market recap from
              scratch. Both report agents use a two-stage process: first collect
              a structured fact pack from grounded search and market context,
              then compose a strict JSON report from those facts.
            </p>
            <div className="br-doc-grid br-doc-grid--two">
              <article>
                <strong>Global report agent</strong>
                <span>
                  Collects recent facts about major indexes, notable movers,
                  macro events, and upcoming catalysts. It then writes a
                  wire-style report with headline, summary, key movements,
                  implications, and watch points.
                </span>
              </article>
              <article>
                <strong>Personal report agent</strong>
                <span>
                  Starts with each onboarded user's watchlist, interests,
                  connected portfolio, top holdings, and current market data.
                  The report is written in second person and focuses on what
                  matters to that user's exposure.
                </span>
              </article>
            </div>
            <div className="br-doc-callout">
              <strong>Traceability by design</strong>
              <span>
                Generated reports persist the model name, generated timestamp,
                source fact pack, portfolio context, and watchlist context. That
                keeps the output inspectable instead of being an opaque chat
                response.
              </span>
            </div>
          </section>

          <section className="br-whitepaper__section" id="api">
            <h2>Application API Surface</h2>
            <p>
              The Flask API exposes focused endpoints that map directly to the
              product workflow. Authenticated routes use the Google ID token in
              the Authorization header, then derive the user document from the
              verified email.
            </p>
            <div
              className="br-whitepaper__table br-whitepaper__table--api"
              role="table"
            >
              <div role="row">
                <b>Endpoint</b>
                <b>Role in product</b>
                <b>Primary integrations</b>
              </div>
              <div role="row">
                <span>/api/user</span>
                <span>
                  Fetches or creates the user profile and onboarding state.
                </span>
                <span>Google Auth, Firestore</span>
              </div>
              <div role="row">
                <span>/api/user/onboarding</span>
                <span>Saves experience, goal, interests, and watchlist.</span>
                <span>Firestore</span>
              </div>
              <div role="row">
                <span>/api/market-summary</span>
                <span>
                  Returns personal report fallback logic, SPY snapshot,
                  watchlist quotes, and watchlist news.
                </span>
                <span>Firestore, Polygon</span>
              </div>
              <div role="row">
                <span>/api/ticker/{`{symbol}`}</span>
                <span>
                  Returns company details, quote snapshot, price change, day
                  range, logo, and recent news.
                </span>
                <span>Polygon</span>
              </div>
              <div role="row">
                <span>/api/chart/timeframe</span>
                <span>
                  Returns chart series for the selected ticker and benchmark
                  overlays such as SPY, QQQ, and DIA.
                </span>
                <span>Polygon</span>
              </div>
              <div role="row">
                <span>/api/snaptrade/connect_url</span>
                <span>Creates a read-only brokerage connection portal.</span>
                <span>SnapTrade</span>
              </div>
              <div role="row">
                <span>/api/portfolio/summary</span>
                <span>
                  Aggregates accounts, balances, positions, top holdings,
                  weights, and recent orders.
                </span>
                <span>SnapTrade, Firestore</span>
              </div>
              <div role="row">
                <span>/api/chatbot/query</span>
                <span>
                  Answers finance-scoped user questions with a professional,
                  educational assistant response.
                </span>
                <span>Gemini</span>
              </div>
            </div>
          </section>

          <section className="br-whitepaper__section" id="infrastructure">
            <h2>Infrastructure and Deployment</h2>
            <p>
              BullRunAI runs on a cloud-based production environment. The
              architecture uses independently deployable containers so the
              frontend, API, and background jobs can evolve without shipping the
              whole system as one unit.
            </p>
            <h3>Deployable Components</h3>
            <div className="br-whitepaper__table" role="table">
              <div role="row">
                <b>Component</b>
                <b>Runtime</b>
                <b>Purpose</b>
              </div>
              <div role="row">
                <span>client/</span>
                <span>React + Vite</span>
                <span>User-facing dashboard and portfolio UI.</span>
              </div>
              <div role="row">
                <span>server/</span>
                <span>Flask + Gunicorn</span>
                <span>
                  API layer for auth, users, market data, portfolio, reports,
                  and chatbot.
                </span>
              </div>
              <div role="row">
                <span>global_report_agent/</span>
                <span>Python Cloud Run Job</span>
                <span>
                  Generates global market reports with Gemini and market
                  context.
                </span>
              </div>
              <div role="row">
                <span>personal_report_agent/</span>
                <span>Python Cloud Run Job</span>
                <span>
                  Generates personalized reports from portfolio and watchlist
                  context.
                </span>
              </div>
            </div>

            <h3>Tech Stack</h3>
            <div className="br-stack-grid">
              <article>
                <h3>Frontend</h3>
                <p>
                  React, Vite, React Router, TanStack Query, Recharts,
                  TradingView widgets, Google OAuth.
                </p>
              </article>
              <article>
                <h3>Backend</h3>
                <p>
                  Python, Flask, Gunicorn, Firestore, Google Auth, SnapTrade
                  SDK, Polygon.io API, Gemini API.
                </p>
              </article>
              <article>
                <h3>Infrastructure</h3>
                <p>
                  Google Cloud Run, Cloud Run Jobs, Cloud Build, Artifact
                  Registry, Firestore, Docker.
                </p>
              </article>
            </div>

            <h3>Deployment Flow</h3>
            <p>
              Each component has its own Dockerfile and Cloud Build config. On
              push to main, Cloud Build can build images, push them to Artifact
              Registry, and deploy services to Cloud Run or update Cloud Run Job
              images.
            </p>
            <pre>{`client/cloudbuild.yaml
server/cloudbuild.yaml
global_report_agent/cloudbuild.yaml
personal_report_agent/cloudbuild.yaml`}</pre>
          </section>

          <section className="br-whitepaper__section" id="guardrails">
            <h2>Guardrails and Product Boundaries</h2>
            <p>
              The product is positioned as research infrastructure, not an
              investment adviser. The UI and backend are designed around market
              education, portfolio awareness, and explanatory context.
            </p>
            <div className="br-doc-grid br-doc-grid--three">
              <article>
                <strong>Financial-topic scope</strong>
                <span>
                  The chatbot checks for finance-related intent before sending a
                  message to Gemini and redirects unrelated questions back to
                  investing topics.
                </span>
              </article>
              <article>
                <strong>Read-only brokerage access</strong>
                <span>
                  SnapTrade connection URLs are created with read access for
                  portfolio context. BullRunAI does not place trades.
                </span>
              </article>
              <article>
                <strong>Fallback behavior</strong>
                <span>
                  If a user does not have a personal report yet, the dashboard
                  serves the latest global report so the experience still has
                  meaningful market context.
                </span>
              </article>
            </div>
          </section>
        </article>
      </main>

      <PublicFooter />
    </div>
  );
}

function AuthPage({ onLoginSuccess }) {
  const location = useLocation();
  const navigate = useNavigate();
  const apiUrl = import.meta.env.VITE_APP_API_URL || "http://localhost:8080";
  const initialEmail = React.useMemo(() => {
    const search = new URLSearchParams(location.search);
    return search.get("email") || "";
  }, [location.search]);
  const [email, setEmail] = React.useState(initialEmail);
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [googleWidth, setGoogleWidth] = React.useState(448);

  React.useEffect(() => {
    setEmail(initialEmail);
  }, [initialEmail]);

  React.useEffect(() => {
    const syncGoogleWidth = () => {
      setGoogleWidth(Math.min(448, Math.max(260, window.innerWidth - 88)));
    };

    syncGoogleWidth();
    window.addEventListener("resize", syncGoogleWidth);
    return () => window.removeEventListener("resize", syncGoogleWidth);
  }, []);

  const handleGoogleSuccess = ({ credential }) => {
    if (!credential) {
      setError("Google did not return a sign-in token.");
      return;
    }

    let payload = {};
    try {
      payload = decodeJwtPayload(credential);
    } catch {
      payload = {};
    }

    onLoginSuccess({
      email: payload.email,
      name: payload.name,
      picture: payload.picture,
      token: credential,
    });
  };

  const handleEmailContinue = async (event) => {
    event.preventDefault();
    const trimmed = email.trim();
    setError("");
    setMessage("");

    if (!EMAIL_PATTERN.test(trimmed)) {
      setError("Enter a valid work email.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch(`${apiUrl}/api/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmed }),
      });

      if (response.status === 201) {
        setMessage(
          "Your trial profile is ready. Continue with Google to open BullRun.",
        );
      } else if (response.status === 409) {
        setMessage(
          "That email is already registered. Continue with Google to sign in.",
        );
      } else {
        const data = await response.json().catch(() => ({}));
        setError(data?.error || "Could not prepare this account.");
      }
    } catch {
      setError("Network error. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="br-auth-screen">
      <button
        type="button"
        className="br-auth-home"
        onClick={() => navigate("/")}
      >
        <img src={brLogo} alt="" />
        BullRun
      </button>

      <section className="br-auth-card" aria-label="BullRun sign in">
        <div className="br-auth-card__mark">
          <img src={brLogo} alt="" />
        </div>
        <h1>Welcome to BullRun</h1>

        <form className="br-auth-form" onSubmit={handleEmailContinue}>
          <label htmlFor="br-auth-email">Your work email</label>
          <div className="br-auth-input">
            <Mail size={18} />
            <input
              id="br-auth-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="me@example.com"
            />
          </div>
          {error ? <p className="br-auth-error">{error}</p> : null}
          {message ? <p className="br-auth-message">{message}</p> : null}
          <button
            type="submit"
            className="br-auth-submit"
            disabled={submitting}
          >
            {submitting ? "Preparing account" : "Continue with email"}
          </button>
        </form>

        <div className="br-auth-divider">
          <span />
          Or
          <span />
        </div>

        <div className="br-google-wrap">
          <GoogleLogin
            onSuccess={handleGoogleSuccess}
            onError={() => setError("Google login failed.")}
            theme="outline"
            size="large"
            shape="pill"
            text="continue_with"
            width={`${googleWidth}`}
          />
        </div>
      </section>
    </main>
  );
}

function SalesPage() {
  const [submitted, setSubmitted] = React.useState(false);

  const handleSubmit = (event) => {
    event.preventDefault();
    setSubmitted(true);
  };
  const goTour = () => openProductTourFullscreen();

  return (
    <div className="br-public-page">
      <PublicNav onOpenTour={goTour} />

      <main className="br-sales">
        <section className="br-sales__copy">
          <h1>Request a demo with the BullRun team.</h1>
          <p>
            See how BullRun can support your investing workflow, portfolio
            review, or team research process.
          </p>

          <div className="br-sales__points">
            <article>
              <LineChart size={25} />
              <p>
                <strong>Personal demo.</strong> Walk through daily briefings,
                watchlists, portfolio context, and research chat.
              </p>
            </article>
            <article>
              <Clock3 size={25} />
              <p>
                <strong>Set up your trial.</strong> Leave with a clear path to
                test BullRun against the names you track.
              </p>
            </article>
          </div>

          <div className="br-sales__tour">
            <p>
              <strong>In the meantime</strong> - watch a short overview of how
              BullRun turns market noise into a portfolio brief.
            </p>
            <button type="button" onClick={goTour}>
              Watch product tour
            </button>
          </div>

          <div className="br-sales__cards">
            <article>
              <Sparkles size={26} />
              <p>
                Built for active investors who want a concise read before the
                market day starts.
              </p>
            </article>
            <article>
              <BarChart3 size={26} />
              <p>
                Designed for teams that need shared context across watchlists
                and portfolio exposure.
              </p>
            </article>
          </div>
        </section>

        <section className="br-sales__panel" aria-label="Sales request form">
          <div className="br-sales__steps">
            <span className="is-active">1</span>
            <b>Contact info</b>
            <i />
            <span>2</span>
            <b>How we can help</b>
          </div>

          <form onSubmit={handleSubmit} className="br-sales-form">
            <div className="br-sales-form__row">
              <label>
                First name
                <input type="text" placeholder="John" required />
              </label>
              <label>
                Last name
                <input type="text" placeholder="Doe" required />
              </label>
            </div>
            <label>
              Company email
              <input type="email" placeholder="john.doe@acme.com" required />
            </label>
            <label>
              Phone number
              <input type="tel" placeholder="+1 555 456 7890" />
            </label>
            <label>
              Company name
              <input type="text" placeholder="Acme Inc." />
            </label>
            <label>
              Team size
              <select defaultValue="">
                <option value="" disabled>
                  Select...
                </option>
                <option>1-5</option>
                <option>6-25</option>
                <option>26-100</option>
                <option>100+</option>
              </select>
            </label>
            <label>
              What should we cover?
              <input
                type="text"
                placeholder="Watchlists, portfolio review, team workflow..."
              />
            </label>
            {submitted ? (
              <p className="br-sales-form__message">
                Thanks. The BullRun team will follow up shortly.
              </p>
            ) : null}
            <button type="submit">
              Continue
              <ArrowRight size={19} />
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}

function Login({ onLoginSuccess = () => {} }) {
  const location = useLocation();

  React.useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    document
      .querySelector(".br-public-page, .br-auth-screen")
      ?.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [location.pathname]);

  if (location.pathname === "/sales") {
    return <SalesPage />;
  }

  if (location.pathname === "/whitepaper") {
    return <WhitepaperPage />;
  }

  if (location.pathname === "/login") {
    return <AuthPage onLoginSuccess={onLoginSuccess} />;
  }

  return <LandingPage />;
}

export default Login;
