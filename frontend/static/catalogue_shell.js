(function () {
    const switcher = document.getElementById('catalogue-switcher');
    if (switcher) {
        const activeCatalogue = switcher.dataset.activeCatalogue || '';
        const catalogues = [
            { key: 'medium', label: 'Factory · Medium Risk', url: '/catalogue/M-01' },
            { key: 'high', label: 'Factory · High Risk', url: '/catalogue/H-01' },
            { key: 'low', label: 'Factory · Low Risk', url: '/catalogue/L-01' },
            { key: 'office', label: 'Incoming Warehouse Office', url: '/catalogue/O-01' }
        ];

        function addOption(item, key) {
            const option = document.createElement('option');
            option.value = item.url;
            option.textContent = item.label;
            option.selected = activeCatalogue === key;
            switcher.appendChild(option);
        }

        catalogues.forEach(item => addOption(item, item.key));
        fetch(`/api/catalogue/custom?v=${Date.now()}`, { cache: 'no-store' })
            .then(response => response.ok ? response.json() : [])
            .then(items => items.forEach(item => addOption({ label: item.title, url: item.view_url }, `custom:${item.slug}`)))
            .catch(error => console.warn('Added catalogue navigation unavailable:', error));

        switcher.addEventListener('change', () => {
            if (switcher.value) window.location.assign(switcher.value);
        });
    }

    const guideStyle = document.createElement('style');
    guideStyle.textContent = `
        .catalogue-guide[hidden] { display: none !important; }
        .catalogue-guide { position: fixed; inset: 0; z-index: 3000; pointer-events: none; color: #e2e8f0; font-family: Inter, "Noto Sans Thai", Tahoma, ui-sans-serif, system-ui, sans-serif; }
        .catalogue-guide-spotlight { position: fixed; z-index: 3001; border: 3px solid #38bdf8; border-radius: 13px; box-shadow: 0 0 0 9999px rgba(2, 8, 23, .78), 0 0 0 7px rgba(56, 189, 248, .18), 0 18px 55px rgba(0,0,0,.35); transition: top .22s ease, left .22s ease, width .22s ease, height .22s ease; }
        .catalogue-guide-spotlight.is-intro { top: 50% !important; left: 50% !important; width: 1px !important; height: 1px !important; border: 0; border-radius: 50%; }
        .catalogue-guide-pointer { position: absolute; top: -37px; right: 10px; min-width: max-content; padding: 7px 11px; border-radius: 8px; background: #7dd3fc; color: #082f49; box-shadow: 0 7px 20px rgba(2,132,199,.34); font-size: .7rem; font-weight: 950; letter-spacing: .02em; }
        .catalogue-guide-pointer::after { content: ""; position: absolute; right: 18px; top: 100%; border: 7px solid transparent; border-top-color: #7dd3fc; }
        .catalogue-guide-spotlight.pointer-below .catalogue-guide-pointer { top: auto; bottom: -37px; }
        .catalogue-guide-spotlight.pointer-below .catalogue-guide-pointer::after { top: auto; bottom: 100%; border-top-color: transparent; border-bottom-color: #7dd3fc; }
        .catalogue-guide-spotlight.is-intro .catalogue-guide-pointer { display: none; }
        .catalogue-guide-card { position: fixed; z-index: 3002; width: min(430px, calc(100vw - 28px)); max-height: min(610px, calc(100vh - 28px)); overflow: auto; border: 1px solid rgba(125, 211, 252, .35); border-radius: 18px; background: linear-gradient(145deg, #091727, #102a43); box-shadow: 0 24px 80px rgba(0,0,0,.48); pointer-events: auto; }
        .catalogue-guide-card.is-intro { top: 50% !important; left: 50% !important; width: min(610px, calc(100vw - 28px)); transform: translate(-50%, -50%); }
        .catalogue-guide-head { padding: 18px 20px 13px; background: radial-gradient(circle at 90% -20%, rgba(14,165,233,.34), transparent 48%); }
        .catalogue-guide-topline { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 9px; }
        .catalogue-guide-kicker { margin: 0; color: #7dd3fc; font-size: .68rem; font-weight: 900; letter-spacing: .13em; text-transform: uppercase; }
        .catalogue-guide-progress { color: #93c5d9; font-size: .7rem; font-weight: 850; white-space: nowrap; }
        .catalogue-guide h2 { margin: 0; color: #fff; font-size: clamp(1.15rem, 3vw, 1.52rem); line-height: 1.25; }
        .catalogue-guide-thai-title { display: block; margin-top: 3px; color: #bae6fd; font-size: .82em; font-weight: 750; }
        .catalogue-guide-body { display: grid; gap: 11px; padding: 14px 20px 18px; }
        .catalogue-guide-copy { margin: 0; color: #c5d5e5; font-size: .84rem; line-height: 1.55; }
        .catalogue-guide-copy.thai { padding-top: 10px; border-top: 1px solid rgba(148,163,184,.16); color: #dbeafe; }
        .catalogue-guide-logic { display: grid; grid-template-columns: auto 1fr; gap: 7px 10px; margin-top: 2px; padding: 11px; border: 1px solid rgba(56,189,248,.22); border-radius: 11px; background: rgba(14,165,233,.08); }
        .catalogue-guide-logic b { color: #7dd3fc; font-size: .72rem; }
        .catalogue-guide-logic span { color: #b9cce0; font-size: .74rem; line-height: 1.42; }
        .catalogue-guide-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 20px 16px; border-top: 1px solid rgba(148,163,184,.15); }
        .catalogue-guide-action-group { display: flex; gap: 7px; }
        .catalogue-guide button { min-height: 36px; padding: 8px 13px; border: 1px solid rgba(148,163,184,.32); border-radius: 9px; cursor: pointer; font: inherit; font-size: .75rem; font-weight: 900; }
        .catalogue-guide-skip, .catalogue-guide-back { color: #cbd5e1; background: rgba(255,255,255,.04); }
        .catalogue-guide-next { border-color: #38bdf8 !important; color: #fff; background: #0284c7; }
        .catalogue-guide button:focus-visible { outline: 3px solid rgba(125,211,252,.45); outline-offset: 2px; }
        .catalogue-guide-back:disabled { opacity: .38; cursor: default; }
        .catalogue-loading[hidden] { display: none !important; }
        .catalogue-loading { position: fixed; inset: 0; z-index: 2800; display: grid; place-items: center; padding: 20px; background: rgba(2, 8, 23, .68); backdrop-filter: blur(7px); font-family: Inter, "Noto Sans Thai", Tahoma, ui-sans-serif, system-ui, sans-serif; }
        .catalogue-loading-card { width: min(440px, 100%); padding: 22px; border: 1px solid rgba(125,211,252,.36); border-radius: 18px; background: linear-gradient(145deg, #091727, #102a43); color: #e2e8f0; box-shadow: 0 25px 75px rgba(0,0,0,.45); }
        .catalogue-loading-top { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
        .catalogue-loading-title { margin: 0; color: #fff; font-size: 1rem; font-weight: 900; line-height: 1.35; }
        .catalogue-loading-percent { color: #7dd3fc; font-size: 1.45rem; font-weight: 950; font-variant-numeric: tabular-nums; }
        .catalogue-loading-thai { margin: 5px 0 0; color: #bae6fd; font-size: .79rem; font-weight: 720; line-height: 1.45; }
        .catalogue-loading-track { height: 11px; margin-top: 17px; overflow: hidden; border: 1px solid rgba(148,163,184,.22); border-radius: 999px; background: rgba(255,255,255,.08); }
        .catalogue-loading-bar { width: 0%; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #0284c7, #38bdf8, #7dd3fc); transition: width .2s ease; }
        .catalogue-loading-note { margin: 10px 0 0; color: #9fb5c9; font-size: .7rem; line-height: 1.4; }
        .catalogue-loading.is-error .catalogue-loading-card { border-color: rgba(248,113,113,.5); }
        .catalogue-loading.is-error .catalogue-loading-percent { color: #fca5a5; }
        .catalogue-loading.is-error .catalogue-loading-bar { background: #ef4444; }
        @media (max-width: 650px) {
            .catalogue-guide-card:not(.is-intro) { left: 14px !important; right: 14px !important; bottom: 14px !important; top: auto !important; width: auto; max-height: 48vh; }
            .catalogue-guide-actions { align-items: stretch; flex-direction: column-reverse; }
            .catalogue-guide-action-group { display: grid; grid-template-columns: 1fr 1fr; }
        }
        @media (prefers-reduced-motion: reduce) { .catalogue-guide-spotlight { transition: none; } }
    `;
    document.head.appendChild(guideStyle);

    const loading = document.createElement('div');
    loading.className = 'catalogue-loading';
    loading.hidden = true;
    loading.setAttribute('role', 'status');
    loading.setAttribute('aria-live', 'polite');
    loading.innerHTML = `
        <section class="catalogue-loading-card">
            <div class="catalogue-loading-top">
                <div><p class="catalogue-loading-title">Loading…</p><p class="catalogue-loading-thai" lang="th">กำลังโหลด…</p></div>
                <strong class="catalogue-loading-percent">0%</strong>
            </div>
            <div class="catalogue-loading-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="catalogue-loading-bar"></div></div>
            <p class="catalogue-loading-note">Please keep this page open · กรุณาเปิดหน้านี้ไว้</p>
        </section>`;
    document.body.appendChild(loading);

    const loadingTitle = loading.querySelector('.catalogue-loading-title');
    const loadingThai = loading.querySelector('.catalogue-loading-thai');
    const loadingPercent = loading.querySelector('.catalogue-loading-percent');
    const loadingTrack = loading.querySelector('.catalogue-loading-track');
    const loadingBar = loading.querySelector('.catalogue-loading-bar');
    let loadingValue = 0;
    let loadingTimer = null;
    let loadingHideTimer = null;

    function setLoadingProgress(value, title, thai) {
        loadingValue = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
        if (title) loadingTitle.textContent = title;
        if (thai) loadingThai.textContent = thai;
        loadingPercent.textContent = `${loadingValue}%`;
        loadingTrack.setAttribute('aria-valuenow', String(loadingValue));
        loadingBar.style.width = `${loadingValue}%`;
    }

    function stopLoadingTimer() {
        if (loadingTimer) window.clearInterval(loadingTimer);
        loadingTimer = null;
    }

    window.CatalogueLoading = {
        get active() { return !loading.hidden; },
        start(options = {}) {
            stopLoadingTimer();
            if (loadingHideTimer) window.clearTimeout(loadingHideTimer);
            loading.classList.remove('is-error');
            loading.hidden = false;
            setLoadingProgress(options.initial ?? 3, options.title || 'Loading catalogue…', options.thai || 'กำลังโหลดแค็ตตาล็อก…');
            const ceiling = Math.max(10, Math.min(96, Number(options.ceiling) || 88));
            loadingTimer = window.setInterval(() => {
                if (loadingValue >= ceiling) return;
                const step = Math.max(1, Math.ceil((ceiling - loadingValue) * .06));
                setLoadingProgress(Math.min(ceiling, loadingValue + step));
            }, 420);
        },
        set: setLoadingProgress,
        finish(title = 'Ready', thai = 'พร้อมใช้งาน') {
            stopLoadingTimer();
            setLoadingProgress(100, title, thai);
            loadingHideTimer = window.setTimeout(() => { loading.hidden = true; }, 420);
        },
        fail(message = 'Loading failed', thai = 'การโหลดไม่สำเร็จ') {
            stopLoadingTimer();
            loading.classList.add('is-error');
            setLoadingProgress(Math.max(1, loadingValue), message, thai);
            loadingHideTimer = window.setTimeout(() => { loading.hidden = true; }, 2600);
        },
        hide() {
            stopLoadingTimer();
            loading.hidden = true;
        }
    };

    const logicBlock = `
        <div class="catalogue-guide-logic">
            <b>1 · PPT</b><span>Floor plan + named clickable room shapes<br>แผนผัง + รูปร่างห้องที่ตั้งชื่อไว้</span>
            <b>2 · DOC</b><span>Current catalogue pages and links<br>หน้าคู่มือและลิงก์ข้อมูลล่าสุด</span>
            <b>3 · BUILD</b><span>The system matches room codes and builds the interactive view<br>ระบบจับคู่รหัสห้องและสร้างหน้าจอแบบโต้ตอบ</span>
        </div>`;

    const viewSteps = [
        {
            title: 'Welcome to Catalogue Explorer', thaiTitle: 'ยินดีต้อนรับสู่ระบบ Catalogue Explorer',
            text: 'This page connects a floor plan to the correct equipment-catalogue pages. The important mental model is: the PowerPoint controls where rooms are; the Google Doc controls what catalogue content is shown.',
            thai: 'หน้านี้เชื่อมแผนผังพื้นที่กับหน้าคู่มืออุปกรณ์ที่ถูกต้อง หลักการสำคัญคือ PowerPoint กำหนดตำแหน่งห้อง ส่วน Google Docs กำหนดเนื้อหาคู่มือที่แสดง',
            extra: logicBlock
        },
        {
            target: '#catalogue-switcher', title: 'Switch between catalogues', thaiTitle: 'สลับระหว่างแค็ตตาล็อก',
            text: 'Choose the factory risk area, office area, or any catalogue added later. Changing this selection opens that catalogue directly.',
            thai: 'เลือกพื้นที่โรงงานตามระดับความเสี่ยง พื้นที่สำนักงาน หรือแค็ตตาล็อกที่เพิ่มภายหลัง เมื่อเปลี่ยนรายการ ระบบจะเปิดแค็ตตาล็อกนั้นทันที'
        },
        {
            target: '.catalogue-map-stage, #map-stage', title: 'Use the floor plan', thaiTitle: 'ใช้งานแผนผังพื้นที่',
            text: 'Coloured outlines are clickable room regions extracted from named shapes in the PowerPoint. Click a room to select it and jump the document to its matching page.',
            thai: 'กรอบสีคือพื้นที่ห้องที่คลิกได้ ซึ่งดึงมาจากรูปร่างที่ตั้งชื่อไว้ใน PowerPoint คลิกห้องเพื่อเลือกและเลื่อนไปยังหน้าคู่มือที่ตรงกัน'
        },
        {
            target: '#room-selector, #room-list', title: 'Room codes are a second navigation path', thaiTitle: 'รหัสห้องเป็นอีกวิธีในการค้นหา',
            text: 'If a room is small or hard to click on the map, select its code here. The selected map area, room code, and document page stay synchronized.',
            thai: 'หากห้องบนแผนผังมีขนาดเล็กหรือคลิกยาก ให้เลือกรหัสห้องตรงนี้ พื้นที่บนแผนผัง รหัสห้อง และหน้าคู่มือจะเปลี่ยนให้ตรงกันเสมอ'
        },
        {
            target: '.pdf-panel', title: 'Read the matching catalogue page', thaiTitle: 'ดูหน้าคู่มือที่ตรงกับห้อง',
            text: 'The document scrolls to the selected room. You can also scroll normally through the full catalogue; the room selection follows the page currently in view.',
            thai: 'เอกสารจะเลื่อนไปยังหน้าของห้องที่เลือก และสามารถเลื่อนดูคู่มือทั้งหมดได้ตามปกติ โดยระบบจะปรับห้องที่เลือกตามหน้าที่กำลังดู'
        },
        {
            target: '.pdf-toolbar-actions, .pdf-panel .panel-title', title: 'Catalogue details and viewing tools', thaiTitle: 'รายละเอียดและเครื่องมือการดู',
            text: 'On built-in catalogues, switch between the catalogue and Machine Capacity. Use zoom and expand for detailed reading. Added catalogues keep the same room-to-document navigation even when these extra controls are unavailable.',
            thai: 'สำหรับแค็ตตาล็อกหลัก สามารถสลับระหว่างคู่มือกับข้อมูลกำลังการผลิตของเครื่องจักร รวมถึงซูมและขยายหน้าจอได้ แค็ตตาล็อกที่เพิ่มใหม่ยังคงใช้การเชื่อมห้องกับเอกสารแบบเดียวกัน'
        },
        {
            target: '#refresh-button', title: 'Refresh content—without changing the map', thaiTitle: 'รีเฟรชเนื้อหาโดยไม่เปลี่ยนแผนผัง',
            text: 'Refresh now checks the saved public Google Docs link immediately. The automatic check runs every five minutes. This updates document content only; upload a new PowerPoint in Catalogue Management when room positions or shapes change.',
            thai: 'ปุ่มรีเฟรชจะตรวจสอบลิงก์ Google Docs ที่บันทึกไว้ทันที และระบบตรวจอัตโนมัติทุก 5 นาที การรีเฟรชจะอัปเดตเฉพาะเนื้อหา หากตำแหน่งหรือรูปร่างห้องเปลี่ยน ต้องอัปโหลด PowerPoint ใหม่ในหน้า Catalogue Management'
        },
        {
            target: '.catalogue-manage-button, a[href^="/catalogue/manage"]', title: 'Update a catalogue safely', thaiTitle: 'อัปเดตแค็ตตาล็อกอย่างถูกต้อง',
            text: 'Open Update Catalogue, choose the catalogue, upload the corrected PowerPoint first, then confirm or paste the public Google Docs link. Save & Rebuild reconnects the rooms to the document. Use Room Names or Machine Mapping only for those specific data corrections.',
            thai: 'เปิด Update Catalogue เลือกแค็ตตาล็อก อัปโหลด PowerPoint ที่แก้ไขแล้วก่อน จากนั้นตรวจสอบหรือวางลิงก์ Google Docs แบบสาธารณะ แล้วกด Save & Rebuild เพื่อเชื่อมห้องกับเอกสารใหม่ ใช้ Room Names หรือ Machine Mapping เฉพาะเมื่อต้องแก้ข้อมูลส่วนนั้น',
            extra: logicBlock
        },
        {
            target: '.catalogue-help-button', title: 'Help is always available', thaiTitle: 'เปิดคู่มือนี้ได้ตลอดเวลา',
            text: 'Select the ? button whenever you need to replay this complete tutorial. Your place in the catalogue is not changed.',
            thai: 'กดปุ่ม ? เพื่อเปิดดูบทแนะนำนี้อีกครั้งได้ตลอดเวลา โดยหน้าคู่มือที่กำลังดูจะไม่เปลี่ยน'
        }
    ];

    const layoutSteps = [
        {
            title: 'Stage 2 Catalogue walkthrough', thaiTitle: 'คู่มือการใช้งาน Stage 2 Catalogue',
            text: 'This is the starting page for the whole catalogue system. It combines interactive floor plans, room-to-catalogue links, machine information, and the tools used to maintain those sources.',
            thai: 'หน้านี้เป็นจุดเริ่มต้นของระบบแค็ตตาล็อกทั้งหมด โดยรวมแผนผังแบบโต้ตอบ การเชื่อมห้องกับหน้าคู่มือ ข้อมูลเครื่องจักร และเครื่องมือสำหรับดูแลแหล่งข้อมูล',
            extra: logicBlock
        },
        {
            target: '.shell-actions', title: 'Specialised catalogue tools', thaiTitle: 'เครื่องมือเฉพาะของแค็ตตาล็อก',
            text: 'Machine Mapping maintains machine names and capacities. Room Names corrects room labels and page mappings. Add Catalogue creates a completely new catalogue from a PowerPoint and Google Doc.',
            thai: 'Machine Mapping ใช้ดูแลชื่อเครื่องจักรและกำลังการผลิต Room Names ใช้แก้ชื่อห้องและการจับคู่หน้า ส่วน Add Catalogue ใช้สร้างแค็ตตาล็อกใหม่จาก PowerPoint และ Google Docs'
        },
        {
            target: '#layout-view-select', title: 'Choose the area you want to explore', thaiTitle: 'เลือกพื้นที่ที่ต้องการดู',
            text: 'Switch between the complete factory, individual risk areas, office floors, and catalogues added later. The map and room overlays update together.',
            thai: 'สลับระหว่างโรงงานทั้งหมด พื้นที่ตามระดับความเสี่ยง ชั้นสำนักงาน และแค็ตตาล็อกที่เพิ่มภายหลัง แผนผังและกรอบห้องจะอัปเดตพร้อมกัน'
        },
        {
            target: '.map-stage', title: 'Click a highlighted room', thaiTitle: 'คลิกห้องที่ไฮไลต์',
            text: 'Each coloured region represents a room. Selecting it opens the room details, where you can continue to its matching catalogue page and equipment information. These clickable regions come from the PowerPoint layout.',
            thai: 'พื้นที่สีแต่ละส่วนแทนห้องหนึ่งห้อง เมื่อเลือกแล้วจะเปิดรายละเอียดห้องและสามารถไปยังหน้าคู่มือกับข้อมูลอุปกรณ์ที่ตรงกันได้ พื้นที่ที่คลิกได้เหล่านี้มาจากแผนผัง PowerPoint'
        },
        {
            target: '.map-controls', title: 'Move and inspect the map', thaiTitle: 'เลื่อนและตรวจสอบแผนผัง',
            text: 'Use +/− to zoom, Fit to show the useful map area, and Lock view to prevent accidental movement. You can also drag or use the mouse wheel; hold Ctrl while scrolling to zoom.',
            thai: 'ใช้ +/− เพื่อซูม กด Fit เพื่อแสดงพื้นที่แผนผังที่เหมาะสม และใช้ Lock view เพื่อป้องกันการเลื่อนโดยไม่ตั้งใจ นอกจากนี้ยังลากหรือใช้ล้อเมาส์ได้ และกด Ctrl ค้างขณะเลื่อนเพื่อซูม'
        },
        {
            target: '#open-catalogue-management', title: 'Update an existing catalogue', thaiTitle: 'อัปเดตแค็ตตาล็อกที่มีอยู่',
            text: 'Open Catalogue Management when a source changes. Select the exact catalogue, upload a corrected PowerPoint first if its layout changed, then confirm the public Google Docs link and choose Save & Rebuild. If only document content changed, use Refresh Google Doc instead.',
            thai: 'เปิด Catalogue Management เมื่อแหล่งข้อมูลเปลี่ยน เลือกแค็ตตาล็อกที่ต้องการ อัปโหลด PowerPoint ที่แก้ไขแล้วก่อนหากแผนผังเปลี่ยน จากนั้นตรวจสอบลิงก์ Google Docs แบบสาธารณะและกด Save & Rebuild หากเปลี่ยนเฉพาะเนื้อหาเอกสารให้ใช้ Refresh Google Doc',
            extra: logicBlock
        },
        {
            target: '.catalogue-help-button', title: 'Replay the walkthrough anytime', thaiTitle: 'เปิดคู่มือนี้อีกครั้งได้ตลอดเวลา',
            text: 'Use this ? button whenever a new team member needs the complete English and Thai walkthrough.',
            thai: 'กดปุ่ม ? เมื่อต้องการเปิดคู่มือภาษาอังกฤษและภาษาไทยฉบับเต็มให้สมาชิกทีมคนใหม่'
        }
    ];

    const managementSteps = [
        {
            title: 'Catalogue Management handover guide', thaiTitle: 'คู่มือส่งมอบระบบ Catalogue Management',
            text: 'Use this page when a catalogue source or layout changes. Always work on one selected catalogue and follow the source order below so the map and document remain easy to verify.',
            thai: 'ใช้หน้านี้เมื่อแหล่งข้อมูลหรือแผนผังของแค็ตตาล็อกเปลี่ยนแปลง ให้เลือกแก้ไขทีละแค็ตตาล็อกและทำตามลำดับด้านล่าง เพื่อให้ตรวจสอบแผนผังและเอกสารได้ง่าย', extra: logicBlock
        },
        {
            target: '#catalogue-select', title: '1. Select the exact catalogue', thaiTitle: '1. เลือกแค็ตตาล็อกที่ต้องการ',
            text: 'This selection scopes every source field below. Check the catalogue name and PowerPoint filename in the summary before editing.',
            thai: 'รายการนี้กำหนดว่าแหล่งข้อมูลด้านล่างเป็นของแค็ตตาล็อกใด ตรวจสอบชื่อแค็ตตาล็อกและชื่อไฟล์ PowerPoint ในสรุปก่อนแก้ไข'
        },
        {
            target: '#pptx-file', title: '2. Upload the PowerPoint first', thaiTitle: '2. อัปโหลด PowerPoint ก่อน',
            text: 'Upload a .pptx only when the floor plan, room boundaries, or room codes changed. The deck must contain the map picture and named AutoShape/Freeform overlays. If the layout is unchanged, leave this field empty.',
            thai: 'อัปโหลดไฟล์ .pptx เมื่อแผนผัง ขอบเขตห้อง หรือรหัสห้องเปลี่ยนเท่านั้น ภายในสไลด์ต้องมีรูปแผนผังและ AutoShape/Freeform ที่ตั้งชื่อไว้ หากแผนผังไม่เปลี่ยนให้เว้นช่องนี้ไว้'
        },
        {
            target: '#layout-grid', title: 'Confirm the slide extraction settings', thaiTitle: 'ตรวจสอบค่าการดึงข้อมูลจากสไลด์',
            text: 'Slide selects the source slide. Picture name selects the floor-plan image (blank can auto-detect where allowed). Export width controls image clarity, not the room mapping logic.',
            thai: 'Slide คือหมายเลขสไลด์ต้นทาง Picture name คือชื่อรูปแผนผัง (บางกรณีเว้นว่างเพื่อให้ระบบหาอัตโนมัติได้) Export width มีผลต่อความคมชัดของภาพ ไม่ได้เปลี่ยนหลักการจับคู่ห้อง'
        },
        {
            target: '#doc-url', title: '3. Add or confirm the Google Docs link', thaiTitle: '3. เพิ่มหรือตรวจสอบลิงก์ Google Docs',
            text: 'Paste the source document URL after the PowerPoint is ready. The document must be shared as “Anyone with the link can view.” Its headings and links provide the catalogue pages matched to the room codes.',
            thai: 'วาง URL ของเอกสารหลังจากเตรียม PowerPoint แล้ว ต้องตั้งค่าการแชร์เป็น “ทุกคนที่มีลิงก์สามารถดูได้” หัวข้อและลิงก์ในเอกสารจะใช้สร้างหน้าคู่มือที่จับคู่กับรหัสห้อง'
        },
        {
            target: '#save-button', title: '4. Save & Rebuild', thaiTitle: '4. บันทึกและสร้างใหม่',
            text: 'This applies the selected catalogue’s sources, extracts the room overlays, reads the document, and rebuilds the interactive catalogue. Wait for the green success message, then open the catalogue and test several rooms.',
            thai: 'ปุ่มนี้จะใช้แหล่งข้อมูลของแค็ตตาล็อกที่เลือก ดึงกรอบห้อง อ่านเอกสาร และสร้างหน้าจอแบบโต้ตอบใหม่ รอข้อความสำเร็จสีเขียว จากนั้นเปิดแค็ตตาล็อกและทดสอบหลาย ๆ ห้อง'
        },
        {
            target: '#refresh-button', title: 'Refresh Google Doc only', thaiTitle: 'รีเฟรชเฉพาะ Google Docs',
            text: 'Use this when only document content changed. It does not upload a PowerPoint or change room geometry. The catalogue viewer also checks the saved document automatically every five minutes.',
            thai: 'ใช้ปุ่มนี้เมื่อเปลี่ยนเฉพาะเนื้อหาเอกสาร ปุ่มนี้จะไม่อัปโหลด PowerPoint หรือเปลี่ยนรูปทรงห้อง และหน้าดูแค็ตตาล็อกจะตรวจเอกสารที่บันทึกไว้อัตโนมัติทุก 5 นาที'
        },
        {
            target: '#tools-panel', title: 'Specialised correction tools', thaiTitle: 'เครื่องมือแก้ไขเฉพาะด้าน',
            text: 'Room Names edits labels and page mappings. Machine Mapping assigns machines and capacities. Create Catalogue adds a separate new catalogue. These tools are not required for a routine document refresh.',
            thai: 'Room Names ใช้แก้ชื่อห้องและการจับคู่หน้า Machine Mapping ใช้กำหนดเครื่องจักรและกำลังการผลิต และ Create Catalogue ใช้เพิ่มแค็ตตาล็อกใหม่ เครื่องมือเหล่านี้ไม่จำเป็นสำหรับการรีเฟรชเอกสารทั่วไป'
        }
    ];

    const createSteps = [
        {
            title: 'Create a new catalogue', thaiTitle: 'สร้างแค็ตตาล็อกใหม่',
            text: 'A new interactive catalogue needs two sources. Prepare the PowerPoint map first, then connect the public Google Docs catalogue. This creates a separate catalogue without overwriting an existing one.',
            thai: 'แค็ตตาล็อกแบบโต้ตอบใหม่ต้องใช้แหล่งข้อมูล 2 ส่วน เตรียมแผนผัง PowerPoint ก่อน แล้วจึงเชื่อม Google Docs แบบสาธารณะ ระบบจะสร้างแค็ตตาล็อกแยกใหม่โดยไม่เขียนทับของเดิม', extra: logicBlock
        },
        {
            target: 'input[name="title"]', title: 'Name the catalogue clearly', thaiTitle: 'ตั้งชื่อแค็ตตาล็อกให้ชัดเจน',
            text: 'Use an area and risk-level name that a future user can recognise, for example “Stage 3 · High Risk”.',
            thai: 'ใช้ชื่อพื้นที่และระดับความเสี่ยงที่ผู้ใช้งานในอนาคตเข้าใจได้ เช่น “Stage 3 · High Risk”'
        },
        {
            target: 'input[name="pptx_file"]', title: '1. Upload the PowerPoint map', thaiTitle: '1. อัปโหลดแผนผัง PowerPoint',
            text: 'The selected slide must contain one floor-plan picture with named AutoShape or Freeform overlays above each room. Friendly names work; including a stable room code such as H-51 is best for long-term maintenance.',
            thai: 'สไลด์ที่เลือกต้องมีรูปแผนผังหนึ่งรูป และมี AutoShape หรือ Freeform ที่ตั้งชื่อวางทับแต่ละห้อง สามารถใช้ชื่อทั่วไปได้ แต่ควรใส่รหัสห้องที่คงที่ เช่น H-51 เพื่อให้ง่ายต่อการดูแลระยะยาว'
        },
        {
            target: '.field-row', title: 'Confirm slide and image quality', thaiTitle: 'ตรวจสอบหมายเลขสไลด์และคุณภาพภาพ',
            text: 'Slide Number is one-based (the first slide is 1). Image Width controls exported map clarity; keep 3600 unless the map is unusually large. Picture Name may stay blank to use the largest picture.',
            thai: 'Slide Number เริ่มนับจาก 1 ส่วน Image Width กำหนดความคมชัดของภาพแผนผัง โดยทั่วไปใช้ 3600 และสามารถเว้น Picture Name เพื่อให้ระบบเลือกรูปที่ใหญ่ที่สุดอัตโนมัติ'
        },
        {
            target: 'input[name="doc_url"]', title: '2. Connect the Google Docs catalogue', thaiTitle: '2. เชื่อมต่อแค็ตตาล็อกจาก Google Docs',
            text: 'Paste the document link only after the map is prepared. Confirm “Anyone with the link can view”; otherwise creation or later automatic refresh will fail.',
            thai: 'วางลิงก์เอกสารหลังจากเตรียมแผนผังแล้ว และตรวจสอบว่าตั้งค่า “ทุกคนที่มีลิงก์สามารถดูได้” มิฉะนั้นการสร้างหรือรีเฟรชอัตโนมัติภายหลังจะไม่สำเร็จ'
        },
        {
            target: '#create-button', title: 'Create, verify, then hand over', thaiTitle: 'สร้าง ตรวจสอบ และส่งมอบ',
            text: 'Create Catalogue extracts the map, matches rooms to document pages, and adds it to every catalogue selector. Open the result and test the map, room buttons, and several document jumps before handover.',
            thai: 'Create Catalogue จะดึงแผนผัง จับคู่ห้องกับหน้าเอกสาร และเพิ่มรายการในตัวเลือกแค็ตตาล็อกทุกแห่ง หลังสร้างแล้วให้เปิดผลลัพธ์และทดสอบแผนผัง ปุ่มห้อง และการเลื่อนไปยังเอกสารหลาย ๆ หน้า'
        }
    ];

    let guideKind = 'view';
    let rawSteps = viewSteps;
    if (document.body.classList.contains('layout-map-page')) {
        guideKind = 'layout'; rawSteps = layoutSteps;
    } else if (document.getElementById('catalogue-form') && document.getElementById('catalogue-select')) {
        guideKind = 'management'; rawSteps = managementSteps;
    } else if (document.getElementById('create-form')) {
        guideKind = 'create'; rawSteps = createSteps;
    }

    const guide = document.createElement('div');
    guide.className = 'catalogue-guide';
    guide.hidden = true;
    guide.setAttribute('role', 'dialog');
    guide.setAttribute('aria-modal', 'true');
    guide.setAttribute('aria-labelledby', 'catalogue-guide-title');
    guide.innerHTML = `
        <div class="catalogue-guide-spotlight is-intro" aria-hidden="true"><span class="catalogue-guide-pointer">Look here · ดูตรงนี้</span></div>
        <section class="catalogue-guide-card is-intro">
            <div class="catalogue-guide-head">
                <div class="catalogue-guide-topline"><p class="catalogue-guide-kicker">Interactive tutorial · คู่มือแนะนำ</p><span class="catalogue-guide-progress"></span></div>
                <h2 id="catalogue-guide-title"></h2>
            </div>
            <div class="catalogue-guide-body"></div>
            <div class="catalogue-guide-actions">
                <button class="catalogue-guide-skip" type="button">Close · ปิด</button>
                <div class="catalogue-guide-action-group">
                    <button class="catalogue-guide-back" type="button">← Back · ย้อนกลับ</button>
                    <button class="catalogue-guide-next" type="button">Next · ถัดไป →</button>
                </div>
            </div>
        </section>`;
    document.body.appendChild(guide);

    const card = guide.querySelector('.catalogue-guide-card');
    const spotlight = guide.querySelector('.catalogue-guide-spotlight');
    const title = guide.querySelector('#catalogue-guide-title');
    const body = guide.querySelector('.catalogue-guide-body');
    const progress = guide.querySelector('.catalogue-guide-progress');
    const backButton = guide.querySelector('.catalogue-guide-back');
    const nextButton = guide.querySelector('.catalogue-guide-next');
    const skipButton = guide.querySelector('.catalogue-guide-skip');
    const storageKey = `catalogue-guide-seen-v2-${guideKind}`;
    const legacyGuideKey = 'catalogue-guide-seen-v1';
    let steps = [];
    let stepIndex = 0;
    let openRetryCount = 0;
    let guideLoadingRetry = null;

    function getTarget(step) {
        return step.target ? document.querySelector(step.target) : null;
    }

    function availableSteps() {
        return rawSteps.filter(step => !step.target || getTarget(step));
    }

    function positionStep() {
        if (guide.hidden || !steps.length) return;
        const step = steps[stepIndex];
        const target = getTarget(step);
        const isIntro = !target;
        card.classList.toggle('is-intro', isIntro);
        spotlight.classList.toggle('is-intro', isIntro);
        if (isIntro) {
            card.style.cssText = '';
            spotlight.style.cssText = '';
            return;
        }

        const rect = target.getBoundingClientRect();
        const padding = 7;
        spotlight.classList.toggle('pointer-below', rect.top < 52);
        spotlight.style.top = `${Math.max(6, rect.top - padding)}px`;
        spotlight.style.left = `${Math.max(6, rect.left - padding)}px`;
        spotlight.style.width = `${Math.min(window.innerWidth - 12, rect.width + padding * 2)}px`;
        spotlight.style.height = `${Math.min(window.innerHeight - 12, rect.height + padding * 2)}px`;

        if (window.innerWidth <= 650) return;
        const gap = 17;
        const cardRect = card.getBoundingClientRect();
        const edge = 14;
        const spaceRight = window.innerWidth - rect.right - gap;
        const spaceLeft = rect.left - gap;
        const spaceBelow = window.innerHeight - rect.bottom - gap;
        const spaceAbove = rect.top - gap;
        let left;
        let top;

        if (spaceRight >= cardRect.width) {
            left = rect.right + gap;
            top = rect.top + (rect.height - cardRect.height) / 2;
        } else if (spaceLeft >= cardRect.width) {
            left = rect.left - cardRect.width - gap;
            top = rect.top + (rect.height - cardRect.height) / 2;
        } else if (spaceBelow >= cardRect.height) {
            // Wide fields have no usable side space. Put the explanation below
            // and align it to the right so the highlighted control stays clear.
            left = rect.right - cardRect.width;
            top = rect.bottom + gap;
        } else if (spaceAbove >= cardRect.height) {
            left = rect.right - cardRect.width;
            top = rect.top - cardRect.height - gap;
        } else {
            // Large panels may fill most of the viewport; keep the card in the
            // least disruptive lower-right corner while preserving the border.
            left = window.innerWidth - cardRect.width - edge;
            top = window.innerHeight - cardRect.height - edge;
        }
        left = Math.max(edge, Math.min(left, window.innerWidth - cardRect.width - edge));
        top = Math.max(edge, Math.min(top, window.innerHeight - cardRect.height - edge));
        card.style.left = `${left}px`;
        card.style.top = `${top}px`;
        card.style.transform = 'none';
        card.style.right = 'auto';
        card.style.bottom = 'auto';
    }

    function renderStep() {
        const step = steps[stepIndex];
        if (!step) return;
        title.innerHTML = `${step.title}<span class="catalogue-guide-thai-title" lang="th">${step.thaiTitle}</span>`;
        body.innerHTML = `<p class="catalogue-guide-copy">${step.text}</p><p class="catalogue-guide-copy thai" lang="th">${step.thai}</p>${step.extra || ''}`;
        progress.textContent = `${stepIndex + 1} / ${steps.length}`;
        backButton.disabled = stepIndex === 0;
        nextButton.textContent = stepIndex === steps.length - 1 ? 'Finish · เสร็จสิ้น' : 'Next · ถัดไป →';
        const target = getTarget(step);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
        window.setTimeout(positionStep, target ? 260 : 0);
        nextButton.focus({ preventScroll: true });
    }

    function closeGuide() {
        guide.hidden = true;
        try { window.localStorage.setItem(storageKey, 'yes'); } catch (_error) { /* Storage may be disabled. */ }
    }

    function openGuide() {
        if (window.CatalogueLoading?.active) {
            if (guideLoadingRetry) window.clearTimeout(guideLoadingRetry);
            guideLoadingRetry = window.setTimeout(openGuide, 500);
            return;
        }
        guideLoadingRetry = null;
        if (guideKind === 'management') {
            const catalogueSelect = document.getElementById('catalogue-select');
            if (catalogueSelect && !catalogueSelect.value) {
                if (catalogueSelect.options.length > 1) {
                    catalogueSelect.selectedIndex = 1;
                    catalogueSelect.dispatchEvent(new Event('change'));
                } else if (openRetryCount < 6) {
                    openRetryCount += 1;
                    window.setTimeout(openGuide, 300);
                    return;
                }
            }
        }
        openRetryCount = 0;
        steps = availableSteps();
        if (!steps.length) return;
        stepIndex = 0;
        guide.hidden = false;
        renderStep();
    }

    function moveStep(direction) {
        const nextIndex = stepIndex + direction;
        if (nextIndex >= steps.length) { closeGuide(); return; }
        if (nextIndex < 0) return;
        stepIndex = nextIndex;
        renderStep();
    }

    nextButton.addEventListener('click', () => moveStep(1));
    backButton.addEventListener('click', () => moveStep(-1));
    skipButton.addEventListener('click', closeGuide);
    document.addEventListener('keydown', event => {
        if (guide.hidden) return;
        if (event.key === 'Escape') closeGuide();
        if (event.key === 'ArrowRight') moveStep(1);
        if (event.key === 'ArrowLeft') moveStep(-1);
    });
    window.addEventListener('resize', positionStep);
    window.addEventListener('scroll', positionStep, true);
    document.querySelectorAll('.catalogue-help-button').forEach(button => button.addEventListener('click', openGuide));

    let hasSeenGuide = false;
    try { hasSeenGuide = window.localStorage.getItem(storageKey) === 'yes'; } catch (_error) { /* Show the guide. */ }
    if (!hasSeenGuide) window.setTimeout(openGuide, 180);
    window.CatalogueTutorial = { open: openGuide, close: closeGuide, legacyGuideKey };
})();
