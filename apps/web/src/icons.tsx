/** ResearchTrace icon set, drawn in code: square-cut strokes with a soft tonal fill. */
import type { SVGProps } from 'react';

export type IconProps = Omit<SVGProps<SVGSVGElement>, 'ref'> & { size?: number | string; strokeWidth?: number | string };
const ring = (x: number, y: number, r: number) => `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;

function icon(stroke: string, tone = '') {
  return function Icon({ size = 18, strokeWidth = 1.6, ...rest }: IconProps) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth}
        strokeLinecap="butt" strokeLinejoin="miter" aria-hidden={rest['aria-label'] ? undefined : true} {...rest}>
        {tone && <path d={tone} fill="currentColor" stroke="none" opacity={0.16} />}
        <path d={stroke} />
      </svg>
    );
  };
}

const file = 'M6 3h9l4 4v14H6zM15 3v4h4';
const fileTone = 'M6 3h9l4 4v14H6z';
const round = ring(12, 12, 9);

export const AlertCircle = icon(`${round}M12 7.5v6M12 15.6v1.6`, round);
export const ArrowLeft = icon('M20 12H5M11 6l-6 6 6 6');
export const ArrowRight = icon('M4 12h15M13 6l6 6-6 6');
export const ArrowUpRight = icon('M6 18 18 6M8 6h10v10');
export const BarChart3 = icon('M3.5 20.5h17M5 14h3.5v6.5H5zM10.2 9h3.6v11.5h-3.6zM15.5 4H19v16.5h-3.5z', 'M10.2 9h3.6v11.5h-3.6z');
export const Bell = icon('M4 17h16M6 17v-6a6 6 0 0 1 12 0v6M10 20.5h4', 'M6 17v-6a6 6 0 0 1 12 0v6z');
export const BookOpen = icon('M12 6.5C10 5 7 4.5 3.5 5v14c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5C17 4.5 14 5 12 6.5zM12 6.5v14', 'M12 6.5C10 5 7 4.5 3.5 5v14c3.5-.5 6.5 0 8.5 1.5z');
export const Check = icon('M4.5 12.5 10 18 19.5 6.5');
export const CheckCircle2 = icon(`${round}M8 12.3l2.8 2.8L16 9.5`, round);
export const ChevronDown = icon('M6 9l6 6 6-6');
export const ChevronLeft = icon('M15 6l-6 6 6 6');
export const ChevronRight = icon('M9 6l6 6-6 6');
export const CircleHelp = icon(`${round}M9.5 9.5a2.5 2.5 0 1 1 3.7 2.2c-.8.45-1.2 1-1.2 1.8M12 15.8v1.6`, round);
export const Clock3 = icon(`${round}M12 7v5.5h4`, round);
export const Code2 = icon('M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14');
export const Download = icon('M12 4v11M7 10.5l5 5 5-5M4 20h16');
export const ExternalLink = icon('M14 4h6v6M20 4l-9 9M18 14v6H4V6h6');
export const Eye = icon(`M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z${ring(12, 12, 3)}`, 'M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z');
export const FileChartColumn = icon(`${file}M9.5 17.5v-3M12.5 17.5v-6M15.5 17.5v-2`, fileTone);
export const FileDown = icon(`${file}M12.5 10.5v6.5M9.8 14.3l2.7 2.7 2.7-2.7`, fileTone);
export const FilePenLine = icon(`${file}M9 18l.6-2.6 4.6-4.6 2 2-4.6 4.6z`, fileTone);
export const FileText = icon(`${file}M9 12h7M9 15.5h7M9 8.5h3`, fileTone);
export const Files = icon('M8 3h8l4 4v11H8zM16 3v4h4M4.5 7v14H15', 'M8 3h8l4 4v11H8z');
export const FlaskConical = icon('M9 3h6M10 3v6.5L4 21h16L14 9.5V3M6.8 15h10.4', 'M6.8 15h10.4L20 21H4z');
export const FolderOpen = icon('M3 19.5V5h6.5l2 2.5H19V9M3 19.5 5.5 9H22l-2.8 10.5z', 'M5.5 9H22l-2.8 10.5H3z');
export const GitCompareArrows = icon(`${ring(6, 6, 2.5)}${ring(18, 18, 2.5)}M6 8.5V18h6M9.5 14.5 13 18l-3.5 3.5M18 15.5V6h-6M14.5 9.5 11 6l3.5-3.5`, `${ring(6, 6, 2.5)}${ring(18, 18, 2.5)}`);
export const Image = icon(`M3.5 4.5h17v15h-17zM3.5 16.5 9 11l4 4 3-3 4.5 4.5${ring(15.5, 8.5, 1.5)}`, 'M3.5 16.5 9 11l4 4 3-3 4.5 4.5v3h-17z');
export const Languages = icon('M3 6h11M8.5 3.5V6M12 6c-1 4-4 7.5-8 9.5M5.5 10c1.5 2.5 3.5 4.3 6 5.5M12.5 21l4.2-10L21 21M14 17.5h5.5');
export const Layers3 = icon('M12 3l9 5-9 5-9-5zM3 12.5l9 5 9-5M3 16.5l9 5 9-5', 'M12 3l9 5-9 5-9-5z');
export const ListChecks = icon('M3.5 6l1.8 1.8L8.5 4.5M3.5 13l1.8 1.8 3.2-3.3M12 6.5h9M12 13h9M12 19.5h9M4 19.5h4');
export const ListTree = icon('M4 5h9M8 5v14h4M8 12h4M15 5h5M15 12h5M15 19h5');
export const LoaderCircle = icon('M12 3a9 9 0 1 0 9 9');
export const LogOut = icon('M10 4H4v16h6M16 7.5l4.5 4.5-4.5 4.5M20.5 12H9');
export const Menu = icon('M4 7h16M4 12h16M4 17h16');
export const MessageSquare = icon('M3.5 4.5h17v13H10L5.5 21v-3.5h-2z', 'M3.5 4.5h17v13H10L5.5 21v-3.5h-2z');
export const Minus = icon('M5 12h14');
export const Network = icon(`${ring(12, 5.5, 2.5)}${ring(5, 18, 2.5)}${ring(19, 18, 2.5)}M10.8 7.7 6.2 15.8M13.2 7.7l4.6 8.1M7.5 18h9`, ring(12, 5.5, 2.5));
export const Play = icon('M7 4.5v15L19.5 12z', 'M7 4.5v15L19.5 12z');
export const Plus = icon('M12 4.5v15M4.5 12h15');
export const RefreshCw = icon('M20 8.5A8.5 8.5 0 0 0 5 6.5L3.5 8.5M3.5 3.5v5h5M4 15.5a8.5 8.5 0 0 0 15 2l1.5-2M20.5 20.5v-5h-5');
export const RotateCw = icon('M20.5 4v5.5H15M20 9.5A8.5 8.5 0 1 0 20.5 13');
export const Search = icon(`${ring(10.5, 10.5, 6.5)}M15.5 15.5 21 21`, ring(10.5, 10.5, 6.5));
export const Send = icon('M3 11 21 3l-8 18-3-7.5zM10 13.5 21 3', 'M3 11 21 3l-8 18-3-7.5z');
export const Settings2 = icon(`M4 7h9M18 7h2M4 17h2M11 17h9${ring(15.5, 7, 2.5)}${ring(8.5, 17, 2.5)}`, `${ring(15.5, 7, 2.5)}${ring(8.5, 17, 2.5)}`);
export const ShieldCheck = icon('M12 3l8 3v6c0 4.5-3.2 7.5-8 9-4.8-1.5-8-4.5-8-9V6zM8.5 12l2.5 2.5 4.5-5', 'M12 3l8 3v6c0 4.5-3.2 7.5-8 9-4.8-1.5-8-4.5-8-9V6z');
export const Sparkles = icon('M11 3.5 13 10l6.5 2-6.5 2-2 6.5L9 14l-6.5-2L9 10zM19 3v4M17 5h4', 'M11 3.5 13 10l6.5 2-6.5 2-2 6.5L9 14l-6.5-2L9 10z');
export const Square = icon('M5 5h14v14H5z');
export const ThumbsDown = icon('M16 13.5 12 21c-1.8 0-2.8-1.2-2.5-3l.5-3.5H3.5L5.5 4H16zM20.5 13.5H16V4h4.5z', 'M16 13.5 12 21c-1.8 0-2.8-1.2-2.5-3l.5-3.5H3.5L5.5 4H16z');
export const ThumbsUp = icon('M8 10.5 12 3c1.8 0 2.8 1.2 2.5 3L14 9.5h6.5L18.5 20H8zM3.5 10.5H8V20H3.5z', 'M8 10.5 12 3c1.8 0 2.8 1.2 2.5 3L14 9.5h6.5L18.5 20H8z');
export const UploadCloud = icon('M12 20.5V10.5M7.8 14.5 12 10.3l4.2 4.2M7 17.5A4.5 4.5 0 0 1 6 8.6a6.5 6.5 0 0 1 12.4.4 4.3 4.3 0 0 1-1.4 8.5');
export const X = icon('M5.5 5.5l13 13M18.5 5.5l-13 13');
export const Bot = icon('M4.5 8.5h15v11h-15zM12 8.5V4M9 13v2M15 13v2M2 13v3M22 13v3', 'M4.5 8.5h15v11h-15z');
export const Database = icon('M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3', 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z');
export const GitBranch = icon(`${ring(6, 5.5, 2.5)}${ring(6, 18.5, 2.5)}${ring(18, 7.5, 2.5)}M6 8v8M18 10c0 4-6 3-10.5 6.5`);
export const Home = icon('M4 11l8-7 8 7v9.5H4zM9.5 20.5V14h5v6.5', 'M4 11l8-7 8 7v9.5H4z');
export const Library = icon('M3.5 4h4.5v16.5H3.5zM10 4h4.5v16.5H10zM16 5.2l3.4-.9 3 15.4-3.4.9z', 'M3.5 4h4.5v16.5H3.5z');
export const MessagesSquare = icon('M3 3.5h13v10H8l-5 4zM19 8h2.5v12.5l-4-3.5H9.5v-1', 'M3 3.5h13v10H8l-5 4z');
export const Quote = icon('M4 6h6v6.5c0 3-1.6 4.8-4.5 5.5M14 6h6v6.5c0 3-1.6 4.8-4.5 5.5M4 12.5h6M14 12.5h6', 'M4 6h6v6.5H4zM14 6h6v6.5h-6z');
export const ScanSearch = icon(`M3.5 8V3.5H8M16 3.5h4.5V8M20.5 16v4.5H16M8 20.5H3.5V16${ring(11.5, 11.5, 3.5)}M14.2 14.2 17 17`, ring(11.5, 11.5, 3.5));
export const Telescope = icon('M3 12.5 17 5l2.5 5-14 7.5zM17 5l1.5-1 3 6-2 1M11 15l-3.2 6.5M11 15l3.2 6.5', 'M3 12.5 17 5l2.5 5-14 7.5z');
export const TriangleAlert = icon('M12 3.5l10 17H2zM12 10v5M12 16.8v1.6', 'M12 3.5l10 17H2z');
export const Wand2 = icon('M4 20 15 9M13 7l4 4M18 3v4M16 5h4M6 4v3M4.5 5.5h3M20 14v3M18.5 15.5h3');
export const Workflow = icon('M3.5 3.5h7v7h-7zM13.5 13.5h7v7h-7zM7 10.5V17h6.5', 'M3.5 3.5h7v7h-7z');
export const Info = icon(`${round}M12 11v6M12 7v1.6`, round);
export const Copy = icon('M9 9h11.5v11.5H9zM15 9V3.5H3.5V15H9', 'M9 9h11.5v11.5H9z');
export const PanelLeft = icon('M3.5 4.5h17v15h-17zM9 4.5v15', 'M3.5 4.5H9v15H3.5z');
export const PanelRight = icon('M3.5 4.5h17v15h-17zM15 4.5v15', 'M15 4.5h5.5v15H15z');
export const Columns2 = icon('M3.5 4.5h17v15h-17zM12 4.5v15', 'M3.5 4.5H12v15H3.5z');

/** The citation bracket: 研证's mark. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className="brand-glyph">
      <rect width="32" height="32" rx="7" fill="var(--accent)" />
      <path d="M12 8H8v16h4M20 8h4v16h-4" fill="none" stroke="#0b0c0e" strokeWidth="2.6" />
      <rect x="13.6" y="13.6" width="4.8" height="4.8" fill="#0b0c0e" />
    </svg>
  );
}
