locals {
  # Fonte: controllers Spring em autoflow/backend/src/main/java/.../presentation.
  # /auth/login do backend é deliberadamente excluído.
  backend_methods = {
    "/auth/cadastro"                                                    = ["POST"]
    "/auth/usuarios"                                                    = ["GET"]
    "/auth/mecanicos"                                                   = ["GET"]
    "/usuarios"                                                         = ["GET", "POST"]
    "/clientes"                                                         = ["GET", "POST"]
    "/clientes/me"                                                      = ["GET"]
    "/clientes/me/ordens-servico"                                       = ["GET"]
    "/clientes/{id}"                                                    = ["GET", "DELETE"]
    "/clientes/{id}/atualizacao"                                        = ["PATCH"]
    "/clientes/{id}/status"                                             = ["PATCH"]
    "/veiculos"                                                         = ["GET", "POST"]
    "/veiculos/{id}"                                                    = ["GET", "DELETE"]
    "/veiculos/{id}/atualizacao"                                        = ["PATCH"]
    "/servicos"                                                         = ["GET", "POST"]
    "/servicos/{id}"                                                    = ["GET", "DELETE"]
    "/servicos/{id}/atualizacao"                                        = ["PATCH"]
    "/servicos/metricas/tempo-medio"                                    = ["GET"]
    "/peca-insumo"                                                      = ["GET", "POST"]
    "/peca-insumo/{id}"                                                 = ["GET", "DELETE"]
    "/peca-insumo/{id}/atualizacao"                                     = ["PATCH"]
    "/ordens-servico"                                                   = ["GET", "POST"]
    "/ordens-servico/{numeroOs}"                                        = ["GET"]
    "/ordens-servico/{numeroOs}/status"                                 = ["GET"]
    "/ordens-servico/metricas/tempo-medio"                              = ["GET"]
    "/ordens-servico/{numeroOs}/servicos"                               = ["POST"]
    "/ordens-servico/{numeroOs}/mecanico"                               = ["PATCH"]
    "/ordens-servico/{numeroOs}/diagnostico/iniciar"                    = ["PATCH"]
    "/ordens-servico/{numeroOs}/diagnostico/laudo"                      = ["PATCH"]
    "/ordens-servico/{numeroOs}/diagnostico/finalizar"                  = ["PATCH"]
    "/ordens-servico/{numeroOs}/servicos/{servicoId}/itens-necessarios" = ["PATCH"]
    "/ordens-servico/{numeroOs}/servicos/{servicoId}/iniciar"           = ["PATCH"]
    "/ordens-servico/{numeroOs}/servicos/{servicoId}/finalizar"         = ["PATCH"]
    "/ordens-servico/{numeroOs}/entregar"                               = ["PATCH"]
    "/ordens-servico/{numeroOs}/reparos-adicionais"                     = ["POST"]
    "/orcamentos"                                                       = ["GET"]
    "/orcamentos/{orcamentoId}"                                         = ["GET"]
    "/orcamentos/{orcamentoId}/pdf"                                     = ["GET"]
    "/orcamentos/{orcamentoId}/aprovar"                                 = ["POST"]
    "/orcamentos/{orcamentoId}/recusar"                                 = ["POST"]
    "/public/ordens-servico/acompanhamento"                             = ["GET"]
    "/public/orcamentos/{orcamentoId}"                                  = ["GET"]
    "/public/orcamentos/{orcamentoId}/pdf"                              = ["GET"]
    "/public/orcamentos/{orcamentoId}/aprovar"                          = ["POST"]
    "/public/orcamentos/{orcamentoId}/recusar"                          = ["POST"]
    "/public/orcamentos/{orcamentoId}/pdf/acompanhamento"               = ["GET"]
    "/public/orcamentos/{orcamentoId}/aprovar/acompanhamento"           = ["POST"]
  }
  backend_paths = toset(keys(local.backend_methods))
  backend_routes = merge([for path, methods in local.backend_methods : {
    for method in methods : "${method} /api${path}" => path
  }]...)
  # /{asset} permite bundles com hash, mas só chega ao Nginx restritivo, nunca
  # ao backend. Não existe ANY, $default nem /api/{proxy+}.
  frontend_routes = toset([
    "/", "/{asset}", "/assets/{proxy+}", "/media/{proxy+}",
    "/login", "/dashboard", "/clientes", "/usuarios", "/veiculos", "/servicos",
    "/peca-insumo", "/ordens-servico", "/ordens-servico/nova", "/ordens-servico/{numeroOs}",
    "/orcamentos", "/orcamentos/{id}", "/reparos-adicionais", "/minha-conta",
    "/minha-conta/minhas-ordens", "/minha-conta/minhas-ordens/{numeroOs}",
    "/public/acompanhamento", "/public/orcamentos/{id}"
  ])
}
