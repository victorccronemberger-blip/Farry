const status = document.getElementById('status');
try {
  const response = await fetch('/api/releases/latest', { cache: 'no-store' });
  if (!response.ok) {
    const data = await response.json();
    document.getElementById('version').textContent = 'Publicação em preparação';
    status.textContent = data.error === 'release_not_found' ? 'Ainda não há uma versão publicada.'
      : 'Servidor ativo. Os downloads serão liberados após a configuração e validação da primeira versão.';
  } else {
    const envelope = await response.json();
    const manifest = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(envelope.manifest), c => c.charCodeAt(0))));
    document.getElementById('version').textContent = `QMoney ${manifest.version}`;
    status.textContent = 'Atualização com integridade e assinatura verificadas pelo launcher.';
    if (manifest.installer) {
      const link = document.getElementById('download');
      link.href = `/downloads/v${encodeURIComponent(manifest.version)}/FarrySetup.exe`;
      link.hidden = false;
    }
    document.getElementById('notes').textContent = manifest.notes || 'Sem notas adicionais.';
    document.getElementById('details').hidden = false;
  }
} catch {
  document.getElementById('version').textContent = 'Consulta indisponível';
  status.textContent = 'Tente novamente em instantes. A instalação existente continua disponível pelo launcher.';
}
