const stages = [
  { src: '/ui/intro/animitor.html', label: '启动动画 1 / 2', duration: 3200 },
  { src: '/ui/intro/xuanzhuan.html', label: '启动动画 2 / 2', duration: 3200 },
];

export function playStartAnimation() {
  return new Promise(resolve => {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const root = document.createElement('section');
    root.className = 'start-animation';
    root.setAttribute('aria-label', '正在进入系统');
    root.innerHTML = '<iframe class="start-animation-frame" title="系统启动动画" sandbox="" tabindex="-1"></iframe><div class="start-animation-meta"><span aria-live="polite"></span><button type="button">跳过动画</button></div>';
    const frame = root.querySelector('iframe');
    const label = root.querySelector('span');
    const skip = root.querySelector('button');
    let stage = -1;
    let timer = 0;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.clearTimeout(timer);
      root.classList.remove('shown');
      window.setTimeout(() => { root.remove(); resolve(); }, 180);
    };
    const advance = () => {
      stage += 1;
      if (stage >= stages.length) return finish();
      const current = stages[stage];
      label.textContent = current.label;
      frame.src = current.src;
      timer = window.setTimeout(advance, reduceMotion ? 250 : current.duration);
    };
    skip.addEventListener('click', finish);
    document.body.append(root);
    requestAnimationFrame(() => root.classList.add('shown'));
    advance();
  });
}
