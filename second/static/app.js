(function () {
  "use strict";

  // A real 1531-rated blitz game from the CC0 Lichess database (https://lichess.org/kvatmony), names changed.
  var SAMPLE_PGN = [
    '[Event "Rated Blitz game"]',
    '[White "Ananya"]',
    '[Black "Opponent"]',
    '[Result "0-1"]',
    "",
    "1. e4 d5 2. exd5 Qxd5 3. d4 Qe6+ 4. Be2 Qe4 5. Nf3 Bg4 6. O-O c6 7. Re1 Bxf3 8. Bxf3 Qg6",
    "9. Be4 f5 10. Bf3 h5 11. Bf4 Nd7 12. d5 c5 13. d6 e6 14. Nc3 h4 15. Nd5 O-O-O",
    "16. Ne7+ Bxe7 17. dxe7 Nxe7 18. Qd6 e5 19. Rxe5 Qxd6 20. Rxf5 Qe6 21. Bg4 Nxf5 0-1",
  ].join("\n");

  function showSource() {
    var checked = document.querySelector('input[name="source"]:checked');
    if (!checked) return;
    document.querySelectorAll(".source").forEach(function (box) {
      box.hidden = box.dataset.source !== checked.value;
    });
    var games = document.getElementById("games");
    if (games) {
      var many = checked.value === "lichess_user" || checked.value === "chesscom_user" || checked.value === "file" || checked.value === "pgn";
      games.closest("div").hidden = !many;
    }
  }

  document.querySelectorAll('input[name="source"]').forEach(function (radio) {
    radio.addEventListener("change", showSource);
  });
  showSource();

  var sample = document.getElementById("sample-pgn");
  if (sample) {
    sample.addEventListener("click", function () {
      document.getElementById("pgn_text").value = SAMPLE_PGN;
      document.getElementById("student_name").value = "Ananya";
      document.getElementById("student_color").value = "white";
    });
  }

  var engineChip = document.getElementById("status-engine");
  if (engineChip) {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (status) {
      engineChip.textContent = status.stockfish ? "Stockfish ready" : "Stockfish not found";
      engineChip.className = "chip " + (status.stockfish ? "ok" : "bad");
      var modelChip = document.getElementById("status-model");
      modelChip.textContent = status.model;
      modelChip.className = "chip " + (status.model_ok ? "ok" : "bad");
    }).catch(function () {});
  }

  var job = document.getElementById("job");
  if (job) {
    var id = job.dataset.job;
    var poll = function () {
      fetch("/api/jobs/" + id).then(function (r) { return r.json(); }).then(function (state) {
        document.getElementById("bar").style.width = Math.round(state.fraction * 100) + "%";
        document.getElementById("message").textContent = state.message;
        if (state.status === "done") {
          if (state.review_ids.length === 1) {
            window.location = "/reviews/" + state.review_ids[0];
            return;
          }
          var links = document.getElementById("links");
          links.innerHTML = "";
          state.review_ids.forEach(function (rid, i) {
            var a = document.createElement("a");
            a.href = "/reviews/" + rid;
            a.className = "button";
            a.textContent = "Game " + (i + 1);
            links.appendChild(a);
            links.appendChild(document.createTextNode(" "));
          });
          return;
        }
        if (state.status === "error") {
          document.getElementById("message").innerHTML = "";
          var p = document.createElement("strong");
          p.textContent = state.message;
          document.getElementById("message").appendChild(p);
          var back = document.createElement("a");
          back.href = "/";
          back.className = "button";
          back.textContent = "Try again";
          document.getElementById("links").appendChild(back);
          return;
        }
        setTimeout(poll, 1000);
      }).catch(function () { setTimeout(poll, 3000); });
    };
    poll();
  }

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = document.querySelector(button.dataset.copy);
      navigator.clipboard.writeText(target.innerText).then(function () {
        button.textContent = "Copied!";
        setTimeout(function () { button.textContent = "Copy"; }, 2000);
      });
    });
  });
})();
