// Graphviz runs in a disposable browser worker, never a host shell or server job.
import { instance } from '@viz-js/viz';
self.onmessage = async (event: MessageEvent<string>) => {
  try {
    if (typeof event.data !== 'string' || event.data.length > 30000) throw new Error('DOT 大小无效');
    const viz = await instance();
    const svg = viz.renderString(event.data, { format: 'svg', engine: 'dot' });
    if (svg.length > 2_000_000) throw new Error('SVG 输出超过限制');
    self.postMessage({ svg });
  } catch {
    self.postMessage({ error: 'DOT 语法或渲染失败；请检查源码。' });
  }
};
