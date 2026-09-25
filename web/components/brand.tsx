/** BCONZ mark + wordmark, as on bconz.com. Text rather than the PNG wordmark
 *  so it stays legible in dark mode. */
export default function Brand({ large = false }: { large?: boolean }) {
  return (
    <span className={large ? "brand brand-lg" : "brand"}>
      <img src="/brand/bconz-icon.png" alt="" width={large ? 40 : 28} height={large ? 42 : 29} />
      <span className="wordmark">BCONZ</span>
      <span className="product">DIA</span>
    </span>
  );
}
