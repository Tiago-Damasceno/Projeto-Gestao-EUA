-- Script SQL de Inicialização: Empresa Matriz 23e Growth e Usuário Master
-- Execute este script no SQL Editor do Supabase.

-- 1. Criar a Empresa Matriz 23e Growth
INSERT INTO public.companies (id, name, slug)
VALUES (
  '00000000-0000-4000-8000-000000000000',
  '23e Growth',
  '23e-growth'
)
ON CONFLICT (slug) DO NOTHING;

-- Instruções para vincular seu usuário Master:
-- 1. Vá em Supabase Dashboard > Authentication > Users
-- 2. Copie o UUID do seu usuário logado (ex: 'SEU_UUID_AQUI')
-- 3. Execute o comando abaixo substituindo SEU_UUID_AQUI pelo seu ID:

/*
INSERT INTO public.company_members (company_id, user_id, role)
VALUES (
  '00000000-0000-4000-8000-000000000000',
  'SEU_UUID_AQUI',
  'platform_admin'
)
ON CONFLICT (company_id, user_id) DO UPDATE SET role = 'platform_admin';
*/
