// Minimal canvas signature pads. Each .sigpad writes a PNG data URL into the
// hidden input named by its data-target attribute, so it saves with the form.
(function () {
  function initPad(canvas) {
    var targetName = canvas.getAttribute('data-target');
    var hidden = document.querySelector('input[name="' + targetName + '"]');
    var ctx = canvas.getContext('2d');
    var drawing = false, last = null, dirty = false;

    // Scale the backing store to the displayed size for crisp lines.
    function size() {
      var r = canvas.getBoundingClientRect();
      canvas.width = r.width;
      canvas.height = r.height;
      ctx.lineWidth = 2;
      ctx.lineCap = 'round';
      ctx.strokeStyle = '#101010';
    }
    size();
    window.addEventListener('resize', size);

    function pos(e) {
      var r = canvas.getBoundingClientRect();
      var p = e.touches ? e.touches[0] : e;
      return { x: p.clientX - r.left, y: p.clientY - r.top };
    }
    function start(e) { drawing = true; last = pos(e); e.preventDefault(); }
    function move(e) {
      if (!drawing) return;
      var p = pos(e);
      ctx.beginPath();
      ctx.moveTo(last.x, last.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      last = p; dirty = true;
      e.preventDefault();
    }
    function end() {
      if (!drawing) return;
      drawing = false;
      if (dirty && hidden) hidden.value = canvas.toDataURL('image/png');
    }

    canvas.addEventListener('mousedown', start);
    canvas.addEventListener('mousemove', move);
    window.addEventListener('mouseup', end);
    canvas.addEventListener('touchstart', start, { passive: false });
    canvas.addEventListener('touchmove', move, { passive: false });
    canvas.addEventListener('touchend', end);

    var clearBtn = canvas.parentNode.querySelector('.sig-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (hidden) hidden.value = '';
        dirty = false;
      });
    }
  }

  document.querySelectorAll('canvas.sigpad').forEach(initPad);
})();
